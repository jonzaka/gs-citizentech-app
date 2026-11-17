output "url_publica" {
  description = "Endereco do MVP"
  value       = "https://${azurerm_public_ip.mvp.fqdn}"
}

output "ip_publico" {
  value = azurerm_public_ip.mvp.ip_address
}

output "ssh" {
  description = "Comando para entrar na VM (so funciona a partir do IP liberado)"
  value       = "ssh ${var.usuario_admin}@${azurerm_public_ip.mvp.fqdn}"
}
