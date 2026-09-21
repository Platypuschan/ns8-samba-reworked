#!/usr/bin/env node

// SPDX-License-Identifier: GPL-3.0-or-later

import fs from "node:fs";
import path from "node:path";

const uiRoot = process.argv[2];
if (!uiRoot) {
  throw new Error("usage: patch-ui.mjs UI_ROOT");
}

function replaceOnce(content, needle, replacement, filename) {
  const first = content.indexOf(needle);
  if (first === -1 || content.indexOf(needle, first + needle.length) !== -1) {
    throw new Error(`expected exactly one UI patch anchor in ${filename}`);
  }
  return content.replace(needle, replacement);
}

const settingsPath = path.join(uiRoot, "src/views/Settings.vue");
let settings = fs.readFileSync(settingsPath, "utf8");
settings = replaceOnce(
  settings,
  "      </cv-row>\n    </cv-grid>\n    <!-- credentials modal -->",
  "      </cv-row>\n      <ReplicationNotifications />\n    </cv-grid>\n    <!-- credentials modal -->",
  settingsPath
);
settings = replaceOnce(
  settings,
  'import CredentialsModal from "@/components/CredentialsModal.vue";',
  'import CredentialsModal from "@/components/CredentialsModal.vue";\nimport ReplicationNotifications from "@/components/ReplicationNotifications.vue";',
  settingsPath
);
settings = replaceOnce(
  settings,
  "  components: { CredentialsModal },",
  "  components: { CredentialsModal, ReplicationNotifications },",
  settingsPath
);
fs.writeFileSync(settingsPath, settings);

const translations = {
  en: {
    action: {
      "configure-remote-domain": "Join remote Active Directory domain",
      "get-replication-monitor": "Read replication notification settings",
      "set-replication-monitor": "Save replication notification settings",
    },
    remote_join: {
      choose_mode_description:
        "Choose whether this instance joins an AD domain on another independent NS8 cluster as a domain controller, or a domain already registered in this cluster as a file server.",
      remote_dc: "Join a remote AD domain as a domain controller",
      file_server: "Join a local AD domain as a file server",
      no_local_domain:
        "No local Active Directory domain is available for the file server option.",
      domain_description:
        "Enter the identity of the existing Active Directory domain and a directly reachable writable domain controller.",
      realm: "AD DNS domain / realm",
      netbios_domain: "NetBIOS domain name",
      existing_dc_address: "Existing domain controller IP address",
      existing_dc_address_helper:
        "This address must provide authoritative AD DNS and be directly reachable from the new controller.",
      ldapservice_password: "Existing ldapservice password",
      ldapservice_password_helper:
        "Use the ldapservice password exported from the existing NS8 Samba provider. The account is not reset.",
      settings_description:
        "Configure the identity and local address of the new domain controller.",
      server_name: "Domain controller name",
      server_alias: "Server alias",
      server_ip_address: "Domain controller IP address",
      server_name_tooltip:
        "Unique Active Directory computer name for the new domain controller. It may contain up to 15 characters and cannot be changed later.",
      join_domain: "Join domain",
      domain_already_exists:
        "This domain is already registered in the local NS8 cluster.",
      joinaddress_ip_conflict:
        "The existing and new domain controller IP addresses must differ.",
      remote_dc_dns_check_failed:
        "The existing domain controller did not answer the required AD DNS lookup.",
      hostname_check_failed:
        "The selected domain controller name already exists in AD DNS.",
      remote_dc_port_check_failed:
        "One or more required TCP ports on the existing domain controller are unreachable.",
    },
    replication_monitor: {
      title: "AD replication notifications",
      description:
        "Check Samba replication every five minutes and send one ntfy alert when a connection reaches the configured number of consecutive failures. A recovered connection can trigger a new alert if it fails again.",
      enabled: "Send ntfy notifications for replication failures",
      base_url: "ntfy server URL",
      base_url_helper:
        "Base URL only; the topic is configured separately. HTTP and HTTPS are supported.",
      topic: "ntfy topic",
      topic_helper: "Use 1-64 letters, numbers, underscores, or hyphens.",
      token: "Access token",
      token_helper: "Bearer token for protected topics.",
      token_configured_helper:
        "A token is stored. Leave this field empty to keep it.",
      clear_token: "Remove the stored access token",
      failure_threshold: "Consecutive failures before notification",
      failure_threshold_helper:
        "The threshold is applied to Samba's own consecutive replication failure counter for each inbound and outbound connection.",
      save: "Save notification settings",
      invalid_url:
        "Enter an HTTP(S) URL without embedded credentials, query, or fragment.",
      invalid_ntfy_url:
        "Enter an HTTP(S) URL without embedded credentials, query, or fragment.",
      invalid_topic: "Use 1-64 letters, numbers, underscores, or hyphens.",
      invalid_ntfy_topic: "Use 1-64 letters, numbers, underscores, or hyphens.",
      invalid_failure_threshold: "Enter a whole number from 1 to 1000.",
      not_domain_controller:
        "Replication monitoring is available only on a domain controller.",
    },
  },
  de: {
    action: {
      "configure-remote-domain": "Entfernte Active-Directory-Domäne beitreten",
      "get-replication-monitor":
        "Einstellungen der Replikationsbenachrichtigung lesen",
      "set-replication-monitor":
        "Einstellungen der Replikationsbenachrichtigung speichern",
    },
    remote_join: {
      choose_mode_description:
        "Wähle, ob diese Instanz einer AD-Domäne in einem anderen, unabhängigen NS8-Cluster als Domänencontroller oder einer bereits in diesem Cluster registrierten Domäne als Dateiserver beitritt.",
      remote_dc: "Entfernter AD-Domäne als Domänencontroller beitreten",
      file_server: "Lokaler AD-Domäne als Dateiserver beitreten",
      no_local_domain:
        "Für die Dateiserver-Option ist keine lokale Active-Directory-Domäne verfügbar.",
      domain_description:
        "Gib die Identität der vorhandenen Active-Directory-Domäne und einen direkt erreichbaren, beschreibbaren Domänencontroller ein.",
      realm: "AD-DNS-Domäne / Realm",
      netbios_domain: "NetBIOS-Domänenname",
      existing_dc_address: "IP-Adresse des vorhandenen Domänencontrollers",
      existing_dc_address_helper:
        "Diese Adresse muss autoritatives AD-DNS bereitstellen und vom neuen Domänencontroller direkt erreichbar sein.",
      ldapservice_password: "Vorhandenes ldapservice-Passwort",
      ldapservice_password_helper:
        "Verwende das vom vorhandenen NS8-Samba-Provider exportierte ldapservice-Passwort. Das Konto wird nicht zurückgesetzt.",
      settings_description:
        "Konfiguriere Identität und lokale Adresse des neuen Domänencontrollers.",
      server_name: "Name des Domänencontrollers",
      server_alias: "Server-Alias",
      server_ip_address: "IP-Adresse des Domänencontrollers",
      server_name_tooltip:
        "Eindeutiger Active-Directory-Computername des neuen Domänencontrollers. Er darf bis zu 15 Zeichen enthalten und kann später nicht geändert werden.",
      join_domain: "Domäne beitreten",
      domain_already_exists:
        "Diese Domäne ist bereits im lokalen NS8-Cluster registriert.",
      joinaddress_ip_conflict:
        "Die IP-Adressen des vorhandenen und des neuen Domänencontrollers müssen unterschiedlich sein.",
      remote_dc_dns_check_failed:
        "Der vorhandene Domänencontroller hat die erforderliche AD-DNS-Abfrage nicht beantwortet.",
      hostname_check_failed:
        "Der gewählte Name des Domänencontrollers ist bereits im AD-DNS vorhanden.",
      remote_dc_port_check_failed:
        "Mindestens ein erforderlicher TCP-Port des vorhandenen Domänencontrollers ist nicht erreichbar.",
    },
    replication_monitor: {
      title: "AD-Replikationsbenachrichtigungen",
      description:
        "Prüft die Samba-Replikation alle fünf Minuten und sendet einmalig eine ntfy-Warnung, sobald eine Verbindung die konfigurierte Anzahl aufeinanderfolgender Fehler erreicht. Nach einer Erholung kann ein erneuter Fehler wieder gemeldet werden.",
      enabled: "ntfy-Benachrichtigungen bei Replikationsfehlern senden",
      base_url: "ntfy-Server-URL",
      base_url_helper:
        "Nur die Basis-URL; das Topic wird separat konfiguriert. HTTP und HTTPS werden unterstützt.",
      topic: "ntfy-Topic",
      topic_helper:
        "Verwende 1-64 Buchstaben, Zahlen, Unterstriche oder Bindestriche.",
      token: "Zugriffstoken",
      token_helper: "Bearer-Token für geschützte Topics.",
      token_configured_helper:
        "Ein Token ist gespeichert. Lasse dieses Feld leer, um es beizubehalten.",
      clear_token: "Gespeichertes Zugriffstoken entfernen",
      failure_threshold: "Aufeinanderfolgende Fehler bis zur Benachrichtigung",
      failure_threshold_helper:
        "Der Grenzwert gilt für Sambas eigenen Zähler aufeinanderfolgender Replikationsfehler jeder eingehenden und ausgehenden Verbindung.",
      save: "Benachrichtigungseinstellungen speichern",
      invalid_url:
        "Gib eine HTTP(S)-URL ohne eingebettete Zugangsdaten, Abfrage oder Fragment ein.",
      invalid_ntfy_url:
        "Gib eine HTTP(S)-URL ohne eingebettete Zugangsdaten, Abfrage oder Fragment ein.",
      invalid_topic:
        "Verwende 1-64 Buchstaben, Zahlen, Unterstriche oder Bindestriche.",
      invalid_ntfy_topic:
        "Verwende 1-64 Buchstaben, Zahlen, Unterstriche oder Bindestriche.",
      invalid_failure_threshold: "Gib eine ganze Zahl von 1 bis 1000 ein.",
      not_domain_controller:
        "Die Replikationsüberwachung ist nur auf einem Domänencontroller verfügbar.",
    },
  },
};

const localeRoot = path.join(uiRoot, "public/i18n");
for (const locale of fs.readdirSync(localeRoot, { withFileTypes: true })) {
  if (!locale.isDirectory()) {
    continue;
  }
  const language = locale.name;
  const additions = translations[language] || translations.en;
  const translationPath = path.join(localeRoot, language, "translation.json");
  const translation = JSON.parse(fs.readFileSync(translationPath, "utf8"));
  translation.action = { ...translation.action, ...additions.action };
  translation.remote_join = additions.remote_join;
  translation.replication_monitor = additions.replication_monitor;
  fs.writeFileSync(
    translationPath,
    JSON.stringify(translation, null, 4) + "\n"
  );
}

const metadataPath = path.join(uiRoot, "public/metadata.json");
const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8"));
metadata.docs.code_url = "https://github.com/Platypuschan/ns8-samba-reworked";
metadata.docs.bug_url =
  "https://github.com/Platypuschan/ns8-samba-reworked/issues";
metadata.source = "ghcr.io/platypuschan/samba";
fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2) + "\n");
