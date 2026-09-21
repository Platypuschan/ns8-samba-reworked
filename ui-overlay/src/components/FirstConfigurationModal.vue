<!--
  Copyright (C) 2025 Nethesis S.r.l.
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <NsWizard
    size="default"
    :visible="isShown"
    :cancelLabel="core.$t('common.cancel')"
    :previousLabel="core.$t('common.previous')"
    :nextLabel="nextLabel"
    :isPreviousDisabled="isFirstStep || loading.configureModule"
    :isNextDisabled="isNextButtonDisabled"
    :isNextLoading="loading.configureModule"
    :isCancelDisabled="true"
    @modal-shown="onModalShown"
    @previousStep="previousStep"
    @nextStep="nextStep"
    auto-hide-off
  >
    <template slot="title">{{ $t("welcome.title") }}</template>
    <template slot="content">
      <cv-form>
        <template v-if="step == 'mode'">
          <div class="mg-bottom-lg">
            {{ $t("remote_join.choose_mode_description") }}
          </div>
          <cv-radio-group vertical>
            <cv-radio-button
              v-model="provisionMode"
              value="remote-dc"
              :label="$t('remote_join.remote_dc')"
            />
            <cv-radio-button
              v-model="provisionMode"
              value="file-server"
              :label="$t('remote_join.file_server')"
              :disabled="loading.listUserDomains || !adDomains.length"
            />
          </cv-radio-group>
          <p v-if="!loading.listUserDomains && !adDomains.length">
            {{ $t("remote_join.no_local_domain") }}
          </p>
        </template>

        <template v-else-if="step == 'domain'">
          <NsInlineNotification
            v-if="error.listUserDomains"
            kind="error"
            :title="$t('action.list-user-domains')"
            :description="error.listUserDomains"
            :showCloseButton="false"
          />
          <cv-skeleton-text
            v-if="loading.listUserDomains"
            :paragraph="true"
            :line-count="4"
            heading
          />
          <template v-else-if="!adDomains.length">
            <NsEmptyState :title="$t('welcome.no_domain_configured')">
              <template #description>
                <div>
                  {{ $t("welcome.no_domain_configured_description") }}
                </div>
                <NsButton
                  kind="ghost"
                  :icon="Events20"
                  @click="goToDomainsAndUsers"
                  class="empty-state-button"
                >
                  {{ $t("welcome.go_to_domains_and_users") }}
                </NsButton>
              </template>
            </NsEmptyState>
          </template>
          <template v-else>
            <div class="mg-bottom-lg">
              <div>{{ $t("welcome.step_domain_description") }}</div>
            </div>
            <NsComboBox
              v-model="adDomain"
              :title="$t('settings.domain')"
              :label="$t('welcome.choose_domain')"
              :invalid-message="error.realm"
              :auto-filter="true"
              :auto-highlight="true"
              :options="adDomains"
              :disabled="loading.listUserDomains"
              light
              class="mg-bottom-6"
              ref="realm"
            />
          </template>
        </template>

        <template v-else-if="step == 'remote-domain'">
          <div class="mg-bottom-lg">
            {{ $t("remote_join.domain_description") }}
          </div>
          <NsTextInput
            v-model.trim="remoteRealm"
            :label="$t('remote_join.realm')"
            :invalid-message="error.realm"
            :disabled="loading.configureModule"
            placeholder="ad.example.com"
            light
            class="mg-bottom-lg"
            ref="realm"
          />
          <NsTextInput
            v-model.trim="netbiosDomain"
            :label="$t('remote_join.netbios_domain')"
            :invalid-message="error.nbdomain"
            :disabled="loading.configureModule"
            maxlength="15"
            light
            class="mg-bottom-lg"
            ref="nbdomain"
          />
          <NsTextInput
            v-model.trim="joinAddress"
            :label="$t('remote_join.existing_dc_address')"
            :helper-text="$t('remote_join.existing_dc_address_helper')"
            :invalid-message="error.joinaddress"
            :disabled="loading.configureModule"
            placeholder="198.51.100.2"
            light
            class="mg-bottom-lg"
            ref="joinaddress"
          />
          <NsTextInput
            v-model="ldapServicePassword"
            type="password"
            :label="$t('remote_join.ldapservice_password')"
            :helper-text="$t('remote_join.ldapservice_password_helper')"
            :invalid-message="error.ldapservice_password"
            :disabled="loading.configureModule"
            autocomplete="new-password"
            light
            class="mg-bottom-3"
            ref="ldapservice_password"
          />
        </template>

        <template v-else-if="step == 'credentials'">
          <div class="mg-bottom-lg">
            {{ $t("welcome.step_credentials_description") }}
          </div>
          <NsTextInput
            v-model.trim="username"
            :label="$t('settings.ad_admin_username')"
            :invalid-message="error.adminuser"
            light
            autocomplete="username"
            class="mg-bottom-lg"
            ref="adminuser"
          />
          <NsTextInput
            v-model="password"
            type="password"
            :label="$t('settings.ad_admin_password')"
            :invalid-message="error.adminpass"
            light
            autocomplete="current-password"
            class="mg-bottom-3"
            ref="adminpass"
          />
        </template>

        <template v-else-if="step == 'settings'">
          <div>
            <div class="mg-bottom-lg">
              {{
                isRemoteDomainController
                  ? $t("remote_join.settings_description")
                  : $t("welcome.step_settings_description")
              }}
            </div>
            <NsTextInput
              v-model.trim="serverName"
              :label="
                isRemoteDomainController
                  ? $t('remote_join.server_name')
                  : $t('settings.file_server_name')
              "
              :invalid-message="error.hostname"
              :disabled="loading.configureModule"
              light
              tooltipAlignment="start"
              tooltipDirection="right"
              class="mg-bottom-lg"
              maxlength="15"
              ref="hostname"
            >
              <template #tooltip>
                <div>
                  {{
                    isRemoteDomainController
                      ? $t("remote_join.server_name_tooltip")
                      : $t("welcome.file_server_name_tooltip")
                  }}
                </div>
              </template>
            </NsTextInput>
            <NsTextInput
              v-model.trim="serverAlias"
              :label="`${
                isRemoteDomainController
                  ? $t('remote_join.server_alias')
                  : $t('settings.file_server_alias')
              } (${$t('common.optional')})`"
              :invalid-message="error.nbalias"
              :disabled="loading.configureModule"
              light
              tooltipAlignment="start"
              tooltipDirection="right"
              class="mg-bottom-lg"
              maxlength="15"
              ref="nbalias"
            >
              <template #tooltip>
                <div>{{ $t("welcome.file_server_alias_tooltip") }}</div>
              </template>
            </NsTextInput>
            <NsComboBox
              v-model="ipAddress"
              :title="
                isRemoteDomainController
                  ? $t('remote_join.server_ip_address')
                  : $t('settings.file_server_ip_address')
              "
              :label="$t('welcome.choose_ip_address')"
              :invalid-message="error.ipaddress"
              :auto-filter="true"
              :auto-highlight="true"
              :options="ipAddresses"
              :disabled="loading.configureModule"
              light
              class="mg-bottom-6"
              ref="ipaddress"
            >
              <template #tooltip>
                <div>{{ $t("welcome.file_server_ip_address_tooltip") }}</div>
              </template>
            </NsComboBox>
            <NsInlineNotification
              v-if="error.configureModule"
              kind="error"
              :title="$t('action.' + configureAction)"
              :description="error.configureModule"
              :showCloseButton="false"
            />
          </div>
        </template>
      </cv-form>
    </template>
  </NsWizard>
</template>

<script>
import { UtilService, TaskService, IconService } from "@nethserver/ns8-ui-lib";
import to from "await-to-js";
import { mapState, mapActions } from "vuex";

export default {
  name: "FirstConfigurationModal",
  mixins: [UtilService, TaskService, IconService],
  props: {
    isShown: {
      type: Boolean,
      default: true,
    },
  },
  data() {
    return {
      step: "",
      provisionMode: "remote-dc",
      adDomain: "",
      adDomains: [],
      remoteRealm: "",
      netbiosDomain: "",
      joinAddress: "",
      ldapServicePassword: "",
      username: "",
      password: "",
      serverName: "",
      serverAlias: "",
      ipAddress: "",
      loading: {
        configureModule: false,
        listUserDomains: true,
      },
      error: {
        configureModule: "",
        listUserDomains: "",
        realm: "",
        nbdomain: "",
        joinaddress: "",
        ldapservice_password: "",
        adminuser: "",
        adminpass: "",
        hostname: "",
        nbalias: "",
        ipaddress: "",
      },
    };
  },
  computed: {
    ...mapState(["core", "instanceName", "configuration"]),
    isRemoteDomainController() {
      return (
        this.provisionMode == "remote-dc" &&
        (!this.configuration || !this.configuration.domain)
      );
    },
    configureAction() {
      return this.isRemoteDomainController
        ? "configure-remote-domain"
        : "configure-module";
    },
    stepIndex() {
      return this.steps.indexOf(this.step);
    },
    isFirstStep() {
      return this.stepIndex == 0;
    },
    isLastStep() {
      return this.stepIndex == this.steps.length - 1;
    },
    nextLabel() {
      if (!this.isLastStep) {
        return this.core.$t("common.next");
      }
      return this.isRemoteDomainController
        ? this.$t("remote_join.join_domain")
        : this.$t("welcome.create_file_server");
    },
    isNextButtonDisabled() {
      return (
        this.loading.configureModule ||
        (this.step == "mode" && !this.provisionMode) ||
        (this.step == "domain" &&
          (this.loading.listUserDomains || !this.adDomain)) ||
        (this.step == "remote-domain" &&
          (!this.remoteRealm ||
            !this.netbiosDomain ||
            !this.joinAddress ||
            !this.ldapServicePassword)) ||
        (this.step == "credentials" && (!this.username || !this.password)) ||
        (this.step == "settings" && (!this.serverName || !this.ipAddress))
      );
    },
    steps() {
      if (!this.configuration) {
        return [];
      }
      if (this.configuration.domain) {
        return ["credentials", "settings"];
      }
      return this.provisionMode == "remote-dc"
        ? ["mode", "remote-domain", "credentials", "settings"]
        : ["mode", "domain", "credentials", "settings"];
    },
    ipAddresses() {
      if (!this.configuration) {
        return [];
      }
      return this.configuration.ipaddress_list.map((ip) => {
        return {
          name: ip.ipaddress,
          label: `${ip.ipaddress} - ${ip.label}`,
          value: ip.ipaddress,
        };
      });
    },
  },
  watch: {
    step: function () {
      if (this.step == "remote-domain") {
        this.focusElement("realm");
      } else if (this.step == "credentials") {
        this.focusElement("adminuser");
      } else if (this.step == "settings") {
        this.focusElement("hostname");
        this.$nextTick(() => {
          if (!this.ipAddress && this.ipAddresses.length == 1) {
            this.ipAddress = this.ipAddresses[0].value;
          }
        });
      }
    },
  },
  methods: {
    ...mapActions(["setAppConfiguredInStore"]),
    onModalShown() {
      this.provisionMode = this.configuration.domain
        ? "file-server"
        : "remote-dc";
      this.step = this.steps[0];
      this.listUserDomains();
    },
    nextStep() {
      if (this.isNextButtonDisabled) {
        return;
      }
      if (this.isLastStep) {
        this.configureModule();
      } else {
        this.step = this.steps[this.stepIndex + 1];
      }
    },
    previousStep() {
      if (!this.isFirstStep) {
        this.step = this.steps[this.stepIndex - 1];
      }
    },
    async listUserDomains() {
      this.loading.listUserDomains = true;
      this.error.listUserDomains = "";
      const taskAction = "list-user-domains";
      const eventId = this.getUuid();

      this.core.$root.$once(
        `${taskAction}-aborted-${eventId}`,
        this.listUserDomainsAborted
      );
      this.core.$root.$once(
        `${taskAction}-completed-${eventId}`,
        this.listUserDomainsCompleted
      );

      const [err] = await to(
        this.createClusterTaskForApp({
          action: taskAction,
          extra: {
            title: this.$t("action." + taskAction),
            isNotificationHidden: true,
            eventId,
          },
        })
      );

      if (err) {
        console.error(`error creating task ${taskAction}`, err);
        this.error.listUserDomains = this.getErrorMessage(err);
        this.loading.listUserDomains = false;
      }
    },
    listUserDomainsAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.listUserDomains = this.$t("error.generic_error");
      this.loading.listUserDomains = false;
    },
    listUserDomainsCompleted(taskContext, taskResult) {
      this.adDomains = taskResult.output.domains
        .filter((domain) => domain.schema == "ad")
        .map((domain) => {
          return {
            name: domain.name,
            label: domain.name,
            value: domain.name,
          };
        });
      this.$nextTick(() => {
        if (this.adDomains.length == 1) {
          this.adDomain = this.adDomains[0].value;
        }
      });
      this.loading.listUserDomains = false;
    },
    async configureModule() {
      this.loading.configureModule = true;
      this.clearErrors();
      this.error.configureModule = "";
      const taskAction = this.configureAction;
      const eventId = this.getUuid();

      this.core.$root.$once(
        `${taskAction}-aborted-${eventId}`,
        this.configureModuleAborted
      );
      this.core.$root.$once(
        `${taskAction}-validation-failed-${eventId}`,
        this.configureModuleValidationFailed
      );
      this.core.$root.$once(
        `${taskAction}-completed-${eventId}`,
        this.configureModuleCompleted
      );

      const data = this.isRemoteDomainController
        ? {
            adminuser: this.username,
            adminpass: this.password,
            realm: this.remoteRealm,
            nbdomain: this.netbiosDomain,
            hostname: this.serverName,
            ipaddress: this.ipAddress,
            joinaddress: this.joinAddress,
            ldapservice_password: this.ldapServicePassword,
            nbalias: this.serverAlias,
          }
        : {
            provision: "join-member",
            adminuser: this.username,
            adminpass: this.password,
            realm: this.configuration.domain || this.adDomain,
            hostname: this.serverName,
            ipaddress: this.ipAddress,
            nbalias: this.serverAlias,
          };

      const [err] = await to(
        this.createModuleTaskForApp(this.instanceName, {
          action: taskAction,
          data,
          extra: {
            title: this.$t("action." + taskAction),
            isNotificationHidden: true,
            eventId,
          },
        })
      );

      if (err) {
        console.error(`error creating task ${taskAction}`, err);
        this.error.configureModule = this.getErrorMessage(err);
        this.loading.configureModule = false;
      }
    },
    configureModuleAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.configureModule = this.$t("error.generic_error");
      this.loading.configureModule = false;
    },
    configureModuleValidationFailed(validationErrors) {
      this.loading.configureModule = false;
      let focusAlreadySet = false;

      for (const validationError of validationErrors) {
        const field = validationError.field;
        if (field === "(root)") {
          this.error.configureModule = this.$t("error.generic_error");
          continue;
        }
        if (validationError.error == "invalid_credentials") {
          this.error.adminuser = this.$t(
            "error.incorrect_username_or_password"
          );
          this.error.adminpass = this.$t(
            "error.incorrect_username_or_password"
          );
        } else if (Object.prototype.hasOwnProperty.call(this.error, field)) {
          this.error[field] = this.getI18nStringWithFallback(
            "remote_join." + validationError.error,
            "error." + validationError.error
          );
        }

        if (!focusAlreadySet) {
          if (
            [
              "realm",
              "nbdomain",
              "joinaddress",
              "ldapservice_password",
            ].includes(field) &&
            this.isRemoteDomainController
          ) {
            this.step = "remote-domain";
          } else if (field == "realm") {
            this.step = "domain";
          } else if (["adminuser", "adminpass"].includes(field)) {
            this.step = "credentials";
          } else if (["hostname", "nbalias", "ipaddress"].includes(field)) {
            this.step = "settings";
          }
          this.$nextTick(() => this.focusElement(field));
          focusAlreadySet = true;
        }
      }
    },
    configureModuleCompleted() {
      this.password = "";
      this.ldapServicePassword = "";
      this.$emit("close");
      this.$nextTick(() => this.$emit("configured"));
      this.loading.configureModule = false;
    },
    goToDomainsAndUsers() {
      this.core.$router.push("/domains");
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";

.mg-bottom-3 {
  margin-bottom: 3rem;
}

.mg-bottom-6 {
  margin-bottom: 6rem;
}
</style>
