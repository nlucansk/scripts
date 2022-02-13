$domain = "<DOMAIN>"
$password = "<PASSWORD_OF_DOMAIN_USER>" | ConvertTo-SecureString -asPlainText -Force
$username = "$domain\<USERNAME_OF_DOMAIN_USER>" 
$credential = New-Object System.Management.Automation.PSCredential($username,$password)
Add-Computer -DomainName $domain -Credential $credential -OUPath "OU=................,DC=domain_name,DC=domain_name_2"

Set-ExecutionPolicy Bypass -Scope Process
