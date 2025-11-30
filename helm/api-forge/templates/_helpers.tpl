{{/*
Return common labels
*/}}
{{- define "api-forge.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.global.labels }}
{{ toYaml .Values.global.labels }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "api-forge.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Service Names
*/}}
{{- define "api-forge.postgres.fullname" -}}
{{ .Release.Name }}-postgres
{{- end }}

{{- define "api-forge.redis.fullname" -}}
{{ .Release.Name }}-redis
{{- end }}

{{- define "api-forge.temporal.fullname" -}}
{{ .Release.Name }}-temporal
{{- end }}

{{- define "api-forge.app.fullname" -}}
{{ .Release.Name }}-app
{{- end }}

{{/*
Secret name helpers
*/}}
{{- define "api-forge.postgres.secretName" -}}
{{- if .Values.postgres.secrets.existingSecret -}}
{{ .Values.postgres.secrets.existingSecret }}
{{- else -}}
{{ .Release.Name }}-postgres-secrets
{{- end -}}
{{- end -}}

{{- define "api-forge.redis.secretName" -}}
{{- if .Values.redis.secrets.existingSecret -}}
{{ .Values.redis.secrets.existingSecret }}
{{- else -}}
{{ .Release.Name }}-redis-secrets
{{- end -}}
{{- end -}}

{{- define "api-forge.app.secretName" -}}
{{- if .Values.app.secrets.existingSecret -}}
{{ .Values.app.secrets.existingSecret }}
{{- else -}}
{{ .Release.Name }}-app-secrets
{{- end -}}
{{- end -}}

{{/*
ConfigMap names
*/}}
{{- define "api-forge.app.configMapName" -}}
{{ .Release.Name }}-app-config
{{- end }}

{{/*
Image helper
*/}}
{{- define "api-forge.image" -}}
{{- if .Values.global.imageRegistry }}
{{ .Values.global.imageRegistry }}/{{ .image }}
{{- else }}
{{ .image }}
{{- end }}
{{- end }}

{{/*
PostgreSQL connection string
*/}}
{{- define "api-forge.postgres.connectionString" -}}
postgresql://{{ .Values.postgres.username }}:{{ .Values.postgres.password }}@postgres:5432/{{ .Values.postgres.database }}?sslmode=require
{{- end }}
