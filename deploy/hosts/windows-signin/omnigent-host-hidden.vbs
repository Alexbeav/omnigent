Option Explicit

Dim shell, command, exitCode
Set shell = CreateObject("WScript.Shell")

Function Quote(value)
    Quote = Chr(34) & Replace(value, Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function

command = "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File " _
    & Quote(WScript.Arguments(0)) _
    & " -Executable " & Quote(WScript.Arguments(1)) _
    & " -Server " & Quote(WScript.Arguments(2)) _
    & " -LogPath " & Quote(WScript.Arguments(3))

exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
