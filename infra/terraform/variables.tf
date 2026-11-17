variable "subscription_id" {
  description = "ID da assinatura do Azure"
  type        = string
}

variable "nome" {
  description = "Nome curto do projeto. Vira o nome dos recursos e o comeco da URL publica."
  type        = string
  default     = "cicloalerta"
}

variable "regiao" {
  description = "Regiao do Azure. Brasil para os dados ficarem no pais."
  type        = string
  default     = "brazilsouth"
}

variable "tamanho_vm" {
  description = "Tamanho da VM"
  type        = string
  default     = "Standard_D2s_v4"
}

variable "usuario_admin" {
  description = "Usuario administrador da VM"
  type        = string
  default     = "azureuser"
}

variable "chave_ssh_publica" {
  description = "Caminho do arquivo da chave SSH publica"
  type        = string
}

variable "ip_admin" {
  description = "IP do grupo liberado para SSH, no formato 1.2.3.4/32"
  type        = string

  validation {
    condition     = can(cidrhost(var.ip_admin, 0)) && !startswith(var.ip_admin, "0.0.0.0")
    error_message = "Informe um IP especifico em formato CIDR. A porta 22 nunca pode abrir para 0.0.0.0/0."
  }
}

variable "repositorio" {
  description = "Repositorio publico no GitHub (dono/nome) de onde a VM baixa o compose"
  type        = string
  default     = "jonzaka/gs-citizentech-app"
}

variable "metrics_user" {
  description = "Usuario que le o /metrics"
  type        = string
  default     = "prometheus"
}

variable "metrics_hash" {
  description = "Hash bcrypt da senha do /metrics (gerado com: caddy hash-password)"
  type        = string
  sensitive   = true
}

variable "bot_api_key" {
  description = "Chave que o bot de triagem usa para criar alertas"
  type        = string
  sensitive   = true
}
