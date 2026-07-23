' ====================================================================
'  _skjult.vbs — hjelper: kjorer en .bat HELT SKJULT (ingen vindu) og
'  logger stdout+stderr til fil. Brukes av start_alt.bat for aa starte
'  tjenester i bakgrunnen slik at de ikke kan lukkes ved et uhell.
'  Argumenter:  0 = sti til .bat   1 = sti til loggfil
' ====================================================================
Option Explicit
Dim sh, q, kommando
Set sh = CreateObject("WScript.Shell")
q = Chr(34)   ' dobbelt-fnutt

' Bygger:  cmd /c ""<bat>" > "<logg>" 2>&1"
kommando = "cmd /c " & q & q & WScript.Arguments(0) & q & _
           " > " & q & WScript.Arguments(1) & q & " 2>&1" & q

' 0 = skjult vindu,  False = ikke vent (returner med en gang)
sh.Run kommando, 0, False
