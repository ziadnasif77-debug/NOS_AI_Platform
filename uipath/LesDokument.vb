' ══════════════════════════════════════════════════════════════════
' NAV Archive — UiPath Invoke Code (VB.NET)
'
' Lim denne koden inn i en «Invoke Code»-aktivitet (Language: VBNet).
'
' Argumenter (opprett i Invoke Code → Arguments):
'   Inn:  FilSti              String   full sti til PDF-en
'   Inn:  ApiUrl              String   f.eks. "http://localhost:8000"
'   Inn:  ApiNokkel           String   verdien av API_NOKKEL
'   Inn:  TidsavbruddSekunder Int32    f.eks. 300
'   Ut:   JobbId              String
'   Ut:   Beslutning          String   APPROVED / REVIEW / REJECTED
'   Ut:   ResultatJson        String   hele felter-payloaden (JSON)
'
' Videre i workflowen: Deserialize JSON på ResultatJson og les
' resultat("felter")("navn"), ("dato"), ("ytelse"), ("fylke") osv.
' ══════════════════════════════════════════════════════════════════

Dim klient As New System.Net.Http.HttpClient()
klient.Timeout = TimeSpan.FromSeconds(60)
klient.DefaultRequestHeaders.Add("X-API-Key", ApiNokkel)

' ── 1) Last opp PDF (multipart) ────────────────────────────────────
Dim skjema As New System.Net.Http.MultipartFormDataContent()
Dim filBytes As Byte() = System.IO.File.ReadAllBytes(FilSti)
Dim filDel As New System.Net.Http.ByteArrayContent(filBytes)
filDel.Headers.ContentType = New System.Net.Http.Headers.MediaTypeHeaderValue("application/pdf")
skjema.Add(filDel, "fil", System.IO.Path.GetFileName(FilSti))

Dim oppSvar = klient.PostAsync(ApiUrl & "/last-opp/", skjema).Result
Dim oppKropp As String = oppSvar.Content.ReadAsStringAsync().Result
If CInt(oppSvar.StatusCode) <> 202 AndAlso CInt(oppSvar.StatusCode) <> 200 Then
    Throw New Exception("Opplasting feilet (" & CInt(oppSvar.StatusCode).ToString() & "): " & oppKropp)
End If
Dim oppJson = Newtonsoft.Json.Linq.JObject.Parse(oppKropp)
JobbId = oppJson("dokument_id").ToString()   ' dokument-id — dekker ALLE sidene

' ── 2) Poll /dokument/{id}/status til DONE eller FAILED ────────────
' Flersidig PDF = én jobb per side; status-endepunktet aggregerer alle.
Dim frist As DateTime = DateTime.UtcNow.AddSeconds(TidsavbruddSekunder)
Dim tilstand As String = ""
Do
    System.Threading.Thread.Sleep(2000)
    Dim stSvar = klient.GetAsync(ApiUrl & "/dokument/" & JobbId & "/status").Result
    Dim stKropp As String = stSvar.Content.ReadAsStringAsync().Result
    tilstand = Newtonsoft.Json.Linq.JObject.Parse(stKropp)("state").ToString()
    If DateTime.UtcNow > frist Then
        Throw New Exception("Tidsavbrudd etter " & TidsavbruddSekunder.ToString() & " s — siste tilstand: " & tilstand)
    End If
Loop While tilstand <> "DONE" AndAlso tilstand <> "FAILED"

If tilstand = "FAILED" Then
    Throw New Exception("Behandling feilet for dokument " & JobbId)
End If

' ── 3) Hent aggregerte forretningsfelter for hele dokumentet ───────
Dim resSvar = klient.GetAsync(ApiUrl & "/dokument/" & JobbId & "/felter").Result
ResultatJson = resSvar.Content.ReadAsStringAsync().Result
If CInt(resSvar.StatusCode) <> 200 Then
    Throw New Exception("Kunne ikke hente felter (" & CInt(resSvar.StatusCode).ToString() & "): " & ResultatJson)
End If
Beslutning = Newtonsoft.Json.Linq.JObject.Parse(ResultatJson)("beslutning").ToString()
