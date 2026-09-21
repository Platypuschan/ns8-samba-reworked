<!--
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <cv-row v-if="!loaded || available || error.getSettings">
    <cv-column>
      <cv-tile light>
        <cv-skeleton-text
          v-if="!loaded"
          :paragraph="true"
          :line-count="5"
          heading
        />
        <template v-else>
          <h3 class="mg-bottom-sm">
            {{ $t("replication_monitor.title") }}
          </h3>
          <p class="mg-bottom-lg">
            {{ $t("replication_monitor.description") }}
          </p>
          <NsInlineNotification
            v-if="error.getSettings"
            kind="error"
            :title="$t('action.get-replication-monitor')"
            :description="error.getSettings"
            :showCloseButton="false"
          />
          <cv-form v-if="available" @submit.prevent="validateAndSave">
            <NsToggle
              v-model="enabled"
              value="replicationNotificationsEnabled"
              :label="$t('replication_monitor.enabled')"
              :disabled="loading.setSettings"
              class="mg-bottom-lg"
            />
            <template v-if="enabled">
              <NsTextInput
                v-model.trim="baseUrl"
                :label="$t('replication_monitor.base_url')"
                :helper-text="$t('replication_monitor.base_url_helper')"
                :invalid-message="error.base_url"
                :disabled="loading.setSettings"
                placeholder="https://ntfy.example.com"
                light
                class="mg-bottom-lg"
                ref="base_url"
              />
              <NsTextInput
                v-model.trim="topic"
                :label="$t('replication_monitor.topic')"
                :helper-text="$t('replication_monitor.topic_helper')"
                :invalid-message="error.topic"
                :disabled="loading.setSettings"
                light
                maxlength="64"
                class="mg-bottom-lg"
                ref="topic"
              />
              <NsTextInput
                v-model="token"
                type="password"
                :label="`${$t('replication_monitor.token')} (${$t(
                  'common.optional'
                )})`"
                :helper-text="tokenHelperText"
                :invalid-message="error.token"
                :disabled="loading.setSettings"
                autocomplete="new-password"
                light
                class="mg-bottom-lg"
                ref="token"
              />
              <NsToggle
                v-if="tokenConfigured && !token"
                v-model="clearToken"
                value="clearReplicationNotificationToken"
                :label="$t('replication_monitor.clear_token')"
                :disabled="loading.setSettings"
                class="mg-bottom-lg"
              />
              <NsTextInput
                v-model.trim="failureThreshold"
                type="number"
                :label="$t('replication_monitor.failure_threshold')"
                :helper-text="
                  $t('replication_monitor.failure_threshold_helper')
                "
                :invalid-message="error.failure_threshold"
                :disabled="loading.setSettings"
                min="1"
                max="1000"
                light
                class="mg-bottom-lg"
                ref="failure_threshold"
              />
            </template>
            <NsInlineNotification
              v-if="error.setSettings"
              kind="error"
              :title="$t('action.set-replication-monitor')"
              :description="error.setSettings"
              :showCloseButton="false"
            />
            <NsButton
              kind="primary"
              :icon="Save20"
              :loading="loading.setSettings"
              :disabled="loading.getSettings || loading.setSettings"
            >
              {{ $t("replication_monitor.save") }}
            </NsButton>
          </cv-form>
        </template>
      </cv-tile>
    </cv-column>
  </cv-row>
</template>

<script>
import to from "await-to-js";
import { mapState } from "vuex";
import { IconService, TaskService, UtilService } from "@nethserver/ns8-ui-lib";

export default {
  name: "ReplicationNotifications",
  mixins: [IconService, TaskService, UtilService],
  data() {
    return {
      loaded: false,
      available: false,
      enabled: false,
      baseUrl: "",
      topic: "",
      token: "",
      tokenConfigured: false,
      clearToken: false,
      failureThreshold: "3",
      loading: {
        getSettings: false,
        setSettings: false,
      },
      error: {
        getSettings: "",
        setSettings: "",
        base_url: "",
        topic: "",
        token: "",
        failure_threshold: "",
      },
    };
  },
  computed: {
    ...mapState(["instanceName", "core"]),
    tokenHelperText() {
      return this.tokenConfigured
        ? this.$t("replication_monitor.token_configured_helper")
        : this.$t("replication_monitor.token_helper");
    },
  },
  created() {
    this.getSettings();
  },
  methods: {
    async getSettings() {
      this.loading.getSettings = true;
      this.error.getSettings = "";
      const taskAction = "get-replication-monitor";
      const eventId = this.getUuid();

      this.core.$root.$once(
        `${taskAction}-aborted-${eventId}`,
        this.getSettingsAborted
      );
      this.core.$root.$once(
        `${taskAction}-completed-${eventId}`,
        this.getSettingsCompleted
      );

      const [err] = await to(
        this.createModuleTaskForApp(this.instanceName, {
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
        this.error.getSettings = this.getErrorMessage(err);
        this.loading.getSettings = false;
        this.loaded = true;
      }
    },
    getSettingsAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.getSettings = this.$t("error.generic_error");
      this.loading.getSettings = false;
      this.loaded = true;
    },
    getSettingsCompleted(taskContext, taskResult) {
      const settings = taskResult.output;
      this.available = settings.available;
      this.enabled = settings.enabled;
      this.baseUrl = settings.base_url;
      this.topic = settings.topic;
      this.failureThreshold = String(settings.failure_threshold);
      this.tokenConfigured = settings.token_configured;
      this.token = "";
      this.clearToken = false;
      this.loading.getSettings = false;
      this.loaded = true;
    },
    validateAndSave() {
      this.error.base_url = "";
      this.error.topic = "";
      this.error.token = "";
      this.error.failure_threshold = "";
      this.error.setSettings = "";

      if (!this.enabled) {
        this.setSettings();
        return;
      }

      let firstInvalidField = "";
      try {
        const url = new URL(this.baseUrl);
        if (
          !["http:", "https:"].includes(url.protocol) ||
          url.username ||
          url.password ||
          url.search ||
          url.hash
        ) {
          throw new Error("invalid URL");
        }
      } catch (exception) {
        this.error.base_url = this.$t("replication_monitor.invalid_url");
        firstInvalidField = "base_url";
      }

      if (!/^[A-Za-z0-9_-]{1,64}$/.test(this.topic)) {
        this.error.topic = this.$t("replication_monitor.invalid_topic");
        firstInvalidField = firstInvalidField || "topic";
      }

      const threshold = Number(this.failureThreshold);
      if (!Number.isInteger(threshold) || threshold < 1 || threshold > 1000) {
        this.error.failure_threshold = this.$t(
          "replication_monitor.invalid_failure_threshold"
        );
        firstInvalidField = firstInvalidField || "failure_threshold";
      }

      if (firstInvalidField) {
        this.focusElement(firstInvalidField);
        return;
      }
      this.setSettings();
    },
    async setSettings() {
      this.loading.setSettings = true;
      const taskAction = "set-replication-monitor";
      const eventId = this.getUuid();

      this.core.$root.$once(
        `${taskAction}-aborted-${eventId}`,
        this.setSettingsAborted
      );
      this.core.$root.$once(
        `${taskAction}-validation-failed-${eventId}`,
        this.setSettingsValidationFailed
      );
      this.core.$root.$once(
        `${taskAction}-completed-${eventId}`,
        this.setSettingsCompleted
      );

      const payload = {
        enabled: this.enabled,
        failure_threshold: Number(this.failureThreshold),
        clear_token: this.clearToken,
      };
      if (this.enabled) {
        payload.base_url = this.baseUrl;
        payload.topic = this.topic;
      }
      if (this.token) {
        payload.token = this.token;
        payload.clear_token = false;
      }

      const [err] = await to(
        this.createModuleTaskForApp(this.instanceName, {
          action: taskAction,
          data: payload,
          extra: {
            title: this.$t("action." + taskAction),
            eventId,
          },
        })
      );

      if (err) {
        console.error(`error creating task ${taskAction}`, err);
        this.error.setSettings = this.getErrorMessage(err);
        this.loading.setSettings = false;
      }
    },
    setSettingsAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.setSettings = this.$t("error.generic_error");
      this.loading.setSettings = false;
    },
    setSettingsValidationFailed(validationErrors) {
      this.loading.setSettings = false;
      let firstInvalidField = "";
      for (const validationError of validationErrors) {
        const field = validationError.field;
        if (
          field !== "(root)" &&
          Object.prototype.hasOwnProperty.call(this.error, field)
        ) {
          this.error[field] = this.getI18nStringWithFallback(
            "replication_monitor." + validationError.error,
            "error." + validationError.error
          );
          firstInvalidField = firstInvalidField || field;
        } else {
          this.error.setSettings = this.$t("error.generic_error");
        }
      }
      if (firstInvalidField) {
        this.focusElement(firstInvalidField);
      }
    },
    setSettingsCompleted() {
      this.loading.setSettings = false;
      this.getSettings();
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";
</style>
