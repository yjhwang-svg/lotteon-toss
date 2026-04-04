$batPath = 'C:\Users\MADUP\Desktop\바이브코딩\performance_yujeong\run_toss_bot.bat'
$action = New-ScheduledTaskAction -Execute $batPath
$trigger = New-ScheduledTaskTrigger -Daily -At '10:00AM'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName 'TossUpdateBot' -Action $action -Trigger $trigger -Settings $settings -Force
