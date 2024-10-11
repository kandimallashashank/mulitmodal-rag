$keyFile = "Lab1-CMPE281.pem"
$acl = Get-Acl $keyFile
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Everyone", "FullControl", "Allow")
$acl.RemoveAccessRule($rule)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Everyone", "Read", "Allow")
$acl.AddAccessRule($rule)
Set-Acl $keyFile $acl
