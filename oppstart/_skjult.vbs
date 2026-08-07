' ====================================================================
'  _skjult.vbs — hjelper: kjorer en .bat HELT SKJULT (ingen vindu) og
'  logger stdout+stderr til fil. Brukes av start_alt.bat for aa starte
'  tjenester i bakgrunnen slik at de ikke kan lukkes ved et uhell.
'  Argumenter:  0 = sti til .bat   1 = sti til loggfil
'
'  LOGGEN LEGGES TIL, IKKE OVER (>> og ikke >).
'  Grunnen er maalt: vakthunden aapner NOYAKTIG samme fil med "a" for
'  aa skrive exitkoden naar API-et doer, mens denne fila brukte ">" som
'  TOMMER den. Loggen viste fem omstarter samme dag og bare EN
'  oppstartsbanner - hver eneste traceback bak dem var slettet. Og
'  vakthundens egen melding sier "se oppstart_api.log for traceback".
'  Filen den peker paa ble toemt av oss.
'
'  Rotasjon foer start slik at den ikke vokser fritt: er loggen over
'  MAKS_MB, flyttes den til <navn>.1 (og en eldre .1 kastes). Vi gjoer
'  det HER fordi det er her filhaandtaket opprettes - naar cmd forst
'  holder fila aapen, kan den ikke doepes om paa Windows.
' ====================================================================
Option Explicit
Dim sh, fso, q, kommando, logg, MAKS_MB
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)   ' dobbelt-fnutt
MAKS_MB = 10

logg = WScript.Arguments(1)

' --- roter naar loggen er blitt stor ------------------------------
If fso.FileExists(logg) Then
    If fso.GetFile(logg).Size > MAKS_MB * 1024 * 1024 Then
        If fso.FileExists(logg & ".1") Then fso.DeleteFile logg & ".1", True
        On Error Resume Next
        fso.MoveFile logg, logg & ".1"
        On Error GoTo 0
    End If
End If

' Bygger:  cmd /c ""<bat>" >> "<logg>" 2>&1"
kommando = "cmd /c " & q & q & WScript.Arguments(0) & q & _
           " >> " & q & logg & q & " 2>&1" & q

' 0 = skjult vindu,  False = ikke vent (returner med en gang)
sh.Run kommando, 0, False
