' 토스 워커를 콘솔 창 없이 백그라운드로 실행한다 (로그온 시 자동 실행용).
Set sh = CreateObject("WScript.Shell")
pythonw = "C:\Users\MADUP\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
script  = "C:\Users\MADUP\Desktop\claudecode\lotteon-toss\toss_worker.py"
sh.Run """" & pythonw & """ """ & script & """", 0, False
