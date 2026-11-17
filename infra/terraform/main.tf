terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
  }

  # State local e fora do repositorio (ver .gitignore).
  backend "local" {}
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # A assinatura de estudante nao deixa registrar todos os provedores de uma vez.
  resource_provider_registrations = "none"
}

locals {
  tags = {
    projeto  = "gs-citizentech"
    ambiente = "mvp"
  }
}

resource "azurerm_resource_group" "mvp" {
  name     = "rg-${var.nome}"
  location = var.regiao
  tags     = local.tags
}

resource "azurerm_virtual_network" "mvp" {
  name                = "vnet-${var.nome}"
  location            = azurerm_resource_group.mvp.location
  resource_group_name = azurerm_resource_group.mvp.name
  address_space       = ["10.20.0.0/24"]
  tags                = local.tags
}

resource "azurerm_subnet" "mvp" {
  name                 = "snet-app"
  resource_group_name  = azurerm_resource_group.mvp.name
  virtual_network_name = azurerm_virtual_network.mvp.name
  address_prefixes     = ["10.20.0.0/26"]
}

resource "azurerm_network_security_group" "mvp" {
  name                = "nsg-${var.nome}"
  location            = azurerm_resource_group.mvp.location
  resource_group_name = azurerm_resource_group.mvp.name
  tags                = local.tags

  # O site: HTTP (redireciona) e HTTPS abertos para todos.
  security_rule {
    name                       = "web"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Administracao: SSH somente a partir do IP do grupo. Nunca 0.0.0.0/0.
  security_rule {
    name                       = "ssh-admin"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ip_admin
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "mvp" {
  subnet_id                 = azurerm_subnet.mvp.id
  network_security_group_id = azurerm_network_security_group.mvp.id
}

resource "azurerm_public_ip" "mvp" {
  name                = "pip-${var.nome}"
  location            = azurerm_resource_group.mvp.location
  resource_group_name = azurerm_resource_group.mvp.name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = var.nome
  tags                = local.tags
}

resource "azurerm_network_interface" "mvp" {
  name                = "nic-${var.nome}"
  location            = azurerm_resource_group.mvp.location
  resource_group_name = azurerm_resource_group.mvp.name
  tags                = local.tags

  ip_configuration {
    name                          = "principal"
    subnet_id                     = azurerm_subnet.mvp.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.mvp.id
  }
}

resource "azurerm_linux_virtual_machine" "mvp" {
  name                  = "vm-${var.nome}"
  location              = azurerm_resource_group.mvp.location
  resource_group_name   = azurerm_resource_group.mvp.name
  size                  = var.tamanho_vm
  admin_username        = var.usuario_admin
  network_interface_ids = [azurerm_network_interface.mvp.id]
  tags                  = local.tags

  # Sem senha: so entra com a chave SSH.
  disable_password_authentication = true

  admin_ssh_key {
    username   = var.usuario_admin
    public_key = file(var.chave_ssh_publica)
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  # Instala o Docker e liga o deploy automatico (ver cloud-init.yaml).
  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml", {
    dominio      = azurerm_public_ip.mvp.fqdn
    repositorio  = var.repositorio
    metrics_user = var.metrics_user
    metrics_hash = var.metrics_hash
    bot_api_key  = var.bot_api_key
  }))

  depends_on = [azurerm_subnet_network_security_group_association.mvp]
}
