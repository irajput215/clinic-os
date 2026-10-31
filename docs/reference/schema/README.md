# app

## Tables

| Name | Columns | Comment | Type |
| ---- | ------- | ------- | ---- |
| [public.appointment_hours](public.appointment_hours.md) | 4 |  | BASE TABLE |
| [public.appointment_notifications](public.appointment_notifications.md) | 12 |  | BASE TABLE |
| [public.appointment_settings](public.appointment_settings.md) | 4 |  | BASE TABLE |
| [public.appointments](public.appointments.md) | 13 |  | BASE TABLE |
| [public.audit_log](public.audit_log.md) | 16 |  | BASE TABLE |
| [public.care_relationships](public.care_relationships.md) | 10 |  | BASE TABLE |
| [public.clinical_record_versions](public.clinical_record_versions.md) | 12 |  | BASE TABLE |
| [public.clinical_records](public.clinical_records.md) | 9 |  | BASE TABLE |
| [public.clinics](public.clinics.md) | 7 |  | BASE TABLE |
| [public.dispatch_attempts](public.dispatch_attempts.md) | 18 |  | BASE TABLE |
| [public.intake_applications](public.intake_applications.md) | 18 |  | BASE TABLE |
| [public.patient_alerts](public.patient_alerts.md) | 9 |  | BASE TABLE |
| [public.patient_consents](public.patient_consents.md) | 11 |  | BASE TABLE |
| [public.patient_emergency_contacts](public.patient_emergency_contacts.md) | 10 |  | BASE TABLE |
| [public.patients](public.patients.md) | 30 |  | BASE TABLE |
| [public.permissions](public.permissions.md) | 3 |  | BASE TABLE |
| [public.pharmacies](public.pharmacies.md) | 11 |  | BASE TABLE |
| [public.practitioner_agreements](public.practitioner_agreements.md) | 7 |  | BASE TABLE |
| [public.practitioner_identifiers](public.practitioner_identifiers.md) | 12 |  | BASE TABLE |
| [public.prescription_events](public.prescription_events.md) | 8 |  | BASE TABLE |
| [public.prescriptions](public.prescriptions.md) | 24 |  | BASE TABLE |
| [public.role_permissions](public.role_permissions.md) | 3 |  | BASE TABLE |
| [public.roles](public.roles.md) | 7 |  | BASE TABLE |
| [public.signup_requests](public.signup_requests.md) | 11 |  | BASE TABLE |
| [public.sop_acknowledgements](public.sop_acknowledgements.md) | 6 |  | BASE TABLE |
| [public.sop_versions](public.sop_versions.md) | 8 |  | BASE TABLE |
| [public.sops](public.sops.md) | 9 |  | BASE TABLE |
| [public.staff_invitations](public.staff_invitations.md) | 8 |  | BASE TABLE |
| [public.step_up_grants](public.step_up_grants.md) | 9 |  | BASE TABLE |
| [public.tenant_settings](public.tenant_settings.md) | 4 |  | BASE TABLE |
| [public.tenants](public.tenants.md) | 9 |  | BASE TABLE |
| [public.tga_approval_events](public.tga_approval_events.md) | 9 |  | BASE TABLE |
| [public.tga_approvals](public.tga_approvals.md) | 23 |  | BASE TABLE |
| [public.user](public.user.md) | 8 |  | BASE TABLE |
| [public.user_roles](public.user_roles.md) | 6 |  | BASE TABLE |

## Stored procedures and functions

| Name | ReturnType | Arguments | Type |
| ---- | ------- | ------- | ---- |
| public.appointment_during | trigger |  | FUNCTION |
| public.appointment_status_guard | trigger |  | FUNCTION |
| public.cash_dist | money | money, money | FUNCTION |
| public.clinos_clinical_record_versions_immutable | trigger |  | FUNCTION |
| public.date_dist | int4 | date, date | FUNCTION |
| public.dispatch_attempts_guard | trigger |  | FUNCTION |
| public.float4_dist | float4 | real, real | FUNCTION |
| public.float8_dist | float8 | double precision, double precision | FUNCTION |
| public.gbt_bit_compress | internal | internal | FUNCTION |
| public.gbt_bit_consistent | bool | internal, bit, smallint, oid, internal | FUNCTION |
| public.gbt_bit_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_bit_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_bit_same | internal | gbtreekey_var, gbtreekey_var, internal | FUNCTION |
| public.gbt_bit_sortsupport | void | internal | FUNCTION |
| public.gbt_bit_union | gbtreekey_var | internal, internal | FUNCTION |
| public.gbt_bool_compress | internal | internal | FUNCTION |
| public.gbt_bool_consistent | bool | internal, boolean, smallint, oid, internal | FUNCTION |
| public.gbt_bool_fetch | internal | internal | FUNCTION |
| public.gbt_bool_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_bool_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_bool_same | internal | gbtreekey2, gbtreekey2, internal | FUNCTION |
| public.gbt_bool_sortsupport | void | internal | FUNCTION |
| public.gbt_bool_union | gbtreekey2 | internal, internal | FUNCTION |
| public.gbt_bpchar_compress | internal | internal | FUNCTION |
| public.gbt_bpchar_consistent | bool | internal, character, smallint, oid, internal | FUNCTION |
| public.gbt_bpchar_sortsupport | void | internal | FUNCTION |
| public.gbt_bytea_compress | internal | internal | FUNCTION |
| public.gbt_bytea_consistent | bool | internal, bytea, smallint, oid, internal | FUNCTION |
| public.gbt_bytea_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_bytea_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_bytea_same | internal | gbtreekey_var, gbtreekey_var, internal | FUNCTION |
| public.gbt_bytea_sortsupport | void | internal | FUNCTION |
| public.gbt_bytea_union | gbtreekey_var | internal, internal | FUNCTION |
| public.gbt_cash_compress | internal | internal | FUNCTION |
| public.gbt_cash_consistent | bool | internal, money, smallint, oid, internal | FUNCTION |
| public.gbt_cash_distance | float8 | internal, money, smallint, oid, internal | FUNCTION |
| public.gbt_cash_fetch | internal | internal | FUNCTION |
| public.gbt_cash_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_cash_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_cash_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_cash_sortsupport | void | internal | FUNCTION |
| public.gbt_cash_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_date_compress | internal | internal | FUNCTION |
| public.gbt_date_consistent | bool | internal, date, smallint, oid, internal | FUNCTION |
| public.gbt_date_distance | float8 | internal, date, smallint, oid, internal | FUNCTION |
| public.gbt_date_fetch | internal | internal | FUNCTION |
| public.gbt_date_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_date_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_date_same | internal | gbtreekey8, gbtreekey8, internal | FUNCTION |
| public.gbt_date_sortsupport | void | internal | FUNCTION |
| public.gbt_date_union | gbtreekey8 | internal, internal | FUNCTION |
| public.gbt_decompress | internal | internal | FUNCTION |
| public.gbt_enum_compress | internal | internal | FUNCTION |
| public.gbt_enum_consistent | bool | internal, anyenum, smallint, oid, internal | FUNCTION |
| public.gbt_enum_fetch | internal | internal | FUNCTION |
| public.gbt_enum_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_enum_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_enum_same | internal | gbtreekey8, gbtreekey8, internal | FUNCTION |
| public.gbt_enum_sortsupport | void | internal | FUNCTION |
| public.gbt_enum_union | gbtreekey8 | internal, internal | FUNCTION |
| public.gbt_float4_compress | internal | internal | FUNCTION |
| public.gbt_float4_consistent | bool | internal, real, smallint, oid, internal | FUNCTION |
| public.gbt_float4_distance | float8 | internal, real, smallint, oid, internal | FUNCTION |
| public.gbt_float4_fetch | internal | internal | FUNCTION |
| public.gbt_float4_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_float4_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_float4_same | internal | gbtreekey8, gbtreekey8, internal | FUNCTION |
| public.gbt_float4_sortsupport | void | internal | FUNCTION |
| public.gbt_float4_union | gbtreekey8 | internal, internal | FUNCTION |
| public.gbt_float8_compress | internal | internal | FUNCTION |
| public.gbt_float8_consistent | bool | internal, double precision, smallint, oid, internal | FUNCTION |
| public.gbt_float8_distance | float8 | internal, double precision, smallint, oid, internal | FUNCTION |
| public.gbt_float8_fetch | internal | internal | FUNCTION |
| public.gbt_float8_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_float8_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_float8_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_float8_sortsupport | void | internal | FUNCTION |
| public.gbt_float8_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_inet_compress | internal | internal | FUNCTION |
| public.gbt_inet_consistent | bool | internal, inet, smallint, oid, internal | FUNCTION |
| public.gbt_inet_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_inet_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_inet_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_inet_sortsupport | void | internal | FUNCTION |
| public.gbt_inet_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_int2_compress | internal | internal | FUNCTION |
| public.gbt_int2_consistent | bool | internal, smallint, smallint, oid, internal | FUNCTION |
| public.gbt_int2_distance | float8 | internal, smallint, smallint, oid, internal | FUNCTION |
| public.gbt_int2_fetch | internal | internal | FUNCTION |
| public.gbt_int2_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_int2_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_int2_same | internal | gbtreekey4, gbtreekey4, internal | FUNCTION |
| public.gbt_int2_sortsupport | void | internal | FUNCTION |
| public.gbt_int2_union | gbtreekey4 | internal, internal | FUNCTION |
| public.gbt_int4_compress | internal | internal | FUNCTION |
| public.gbt_int4_consistent | bool | internal, integer, smallint, oid, internal | FUNCTION |
| public.gbt_int4_distance | float8 | internal, integer, smallint, oid, internal | FUNCTION |
| public.gbt_int4_fetch | internal | internal | FUNCTION |
| public.gbt_int4_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_int4_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_int4_same | internal | gbtreekey8, gbtreekey8, internal | FUNCTION |
| public.gbt_int4_sortsupport | void | internal | FUNCTION |
| public.gbt_int4_union | gbtreekey8 | internal, internal | FUNCTION |
| public.gbt_int8_compress | internal | internal | FUNCTION |
| public.gbt_int8_consistent | bool | internal, bigint, smallint, oid, internal | FUNCTION |
| public.gbt_int8_distance | float8 | internal, bigint, smallint, oid, internal | FUNCTION |
| public.gbt_int8_fetch | internal | internal | FUNCTION |
| public.gbt_int8_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_int8_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_int8_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_int8_sortsupport | void | internal | FUNCTION |
| public.gbt_int8_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_intv_compress | internal | internal | FUNCTION |
| public.gbt_intv_consistent | bool | internal, interval, smallint, oid, internal | FUNCTION |
| public.gbt_intv_decompress | internal | internal | FUNCTION |
| public.gbt_intv_distance | float8 | internal, interval, smallint, oid, internal | FUNCTION |
| public.gbt_intv_fetch | internal | internal | FUNCTION |
| public.gbt_intv_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_intv_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_intv_same | internal | gbtreekey32, gbtreekey32, internal | FUNCTION |
| public.gbt_intv_sortsupport | void | internal | FUNCTION |
| public.gbt_intv_union | gbtreekey32 | internal, internal | FUNCTION |
| public.gbt_macad8_compress | internal | internal | FUNCTION |
| public.gbt_macad8_consistent | bool | internal, macaddr8, smallint, oid, internal | FUNCTION |
| public.gbt_macad8_fetch | internal | internal | FUNCTION |
| public.gbt_macad8_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_macad8_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_macad8_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_macad8_sortsupport | void | internal | FUNCTION |
| public.gbt_macad8_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_macad_compress | internal | internal | FUNCTION |
| public.gbt_macad_consistent | bool | internal, macaddr, smallint, oid, internal | FUNCTION |
| public.gbt_macad_fetch | internal | internal | FUNCTION |
| public.gbt_macad_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_macad_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_macad_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_macad_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_macaddr_sortsupport | void | internal | FUNCTION |
| public.gbt_numeric_compress | internal | internal | FUNCTION |
| public.gbt_numeric_consistent | bool | internal, numeric, smallint, oid, internal | FUNCTION |
| public.gbt_numeric_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_numeric_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_numeric_same | internal | gbtreekey_var, gbtreekey_var, internal | FUNCTION |
| public.gbt_numeric_sortsupport | void | internal | FUNCTION |
| public.gbt_numeric_union | gbtreekey_var | internal, internal | FUNCTION |
| public.gbt_oid_compress | internal | internal | FUNCTION |
| public.gbt_oid_consistent | bool | internal, oid, smallint, oid, internal | FUNCTION |
| public.gbt_oid_distance | float8 | internal, oid, smallint, oid, internal | FUNCTION |
| public.gbt_oid_fetch | internal | internal | FUNCTION |
| public.gbt_oid_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_oid_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_oid_same | internal | gbtreekey8, gbtreekey8, internal | FUNCTION |
| public.gbt_oid_sortsupport | void | internal | FUNCTION |
| public.gbt_oid_union | gbtreekey8 | internal, internal | FUNCTION |
| public.gbt_text_compress | internal | internal | FUNCTION |
| public.gbt_text_consistent | bool | internal, text, smallint, oid, internal | FUNCTION |
| public.gbt_text_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_text_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_text_same | internal | gbtreekey_var, gbtreekey_var, internal | FUNCTION |
| public.gbt_text_sortsupport | void | internal | FUNCTION |
| public.gbt_text_union | gbtreekey_var | internal, internal | FUNCTION |
| public.gbt_time_compress | internal | internal | FUNCTION |
| public.gbt_time_consistent | bool | internal, time without time zone, smallint, oid, internal | FUNCTION |
| public.gbt_time_distance | float8 | internal, time without time zone, smallint, oid, internal | FUNCTION |
| public.gbt_time_fetch | internal | internal | FUNCTION |
| public.gbt_time_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_time_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_time_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_time_sortsupport | void | internal | FUNCTION |
| public.gbt_time_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_timetz_compress | internal | internal | FUNCTION |
| public.gbt_timetz_consistent | bool | internal, time with time zone, smallint, oid, internal | FUNCTION |
| public.gbt_ts_compress | internal | internal | FUNCTION |
| public.gbt_ts_consistent | bool | internal, timestamp without time zone, smallint, oid, internal | FUNCTION |
| public.gbt_ts_distance | float8 | internal, timestamp without time zone, smallint, oid, internal | FUNCTION |
| public.gbt_ts_fetch | internal | internal | FUNCTION |
| public.gbt_ts_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_ts_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_ts_same | internal | gbtreekey16, gbtreekey16, internal | FUNCTION |
| public.gbt_ts_sortsupport | void | internal | FUNCTION |
| public.gbt_ts_union | gbtreekey16 | internal, internal | FUNCTION |
| public.gbt_tstz_compress | internal | internal | FUNCTION |
| public.gbt_tstz_consistent | bool | internal, timestamp with time zone, smallint, oid, internal | FUNCTION |
| public.gbt_tstz_distance | float8 | internal, timestamp with time zone, smallint, oid, internal | FUNCTION |
| public.gbt_uuid_compress | internal | internal | FUNCTION |
| public.gbt_uuid_consistent | bool | internal, uuid, smallint, oid, internal | FUNCTION |
| public.gbt_uuid_fetch | internal | internal | FUNCTION |
| public.gbt_uuid_penalty | internal | internal, internal, internal | FUNCTION |
| public.gbt_uuid_picksplit | internal | internal, internal | FUNCTION |
| public.gbt_uuid_same | internal | gbtreekey32, gbtreekey32, internal | FUNCTION |
| public.gbt_uuid_sortsupport | void | internal | FUNCTION |
| public.gbt_uuid_union | gbtreekey32 | internal, internal | FUNCTION |
| public.gbt_var_decompress | internal | internal | FUNCTION |
| public.gbt_var_fetch | internal | internal | FUNCTION |
| public.gbt_varbit_sortsupport | void | internal | FUNCTION |
| public.gbtreekey16_in | gbtreekey16 | cstring | FUNCTION |
| public.gbtreekey16_out | cstring | gbtreekey16 | FUNCTION |
| public.gbtreekey2_in | gbtreekey2 | cstring | FUNCTION |
| public.gbtreekey2_out | cstring | gbtreekey2 | FUNCTION |
| public.gbtreekey32_in | gbtreekey32 | cstring | FUNCTION |
| public.gbtreekey32_out | cstring | gbtreekey32 | FUNCTION |
| public.gbtreekey4_in | gbtreekey4 | cstring | FUNCTION |
| public.gbtreekey4_out | cstring | gbtreekey4 | FUNCTION |
| public.gbtreekey8_in | gbtreekey8 | cstring | FUNCTION |
| public.gbtreekey8_out | cstring | gbtreekey8 | FUNCTION |
| public.gbtreekey_var_in | gbtreekey_var | cstring | FUNCTION |
| public.gbtreekey_var_out | cstring | gbtreekey_var | FUNCTION |
| public.gist_translate_cmptype_btree | int2 | integer | FUNCTION |
| public.int2_dist | int2 | smallint, smallint | FUNCTION |
| public.int4_dist | int4 | integer, integer | FUNCTION |
| public.int8_dist | int8 | bigint, bigint | FUNCTION |
| public.interval_dist | interval | interval, interval | FUNCTION |
| public.oid_dist | oid | oid, oid | FUNCTION |
| public.prescriptions_lock_signed | trigger |  | FUNCTION |
| public.tga_approval_interval | trigger |  | FUNCTION |
| public.tga_approval_lock_verified | trigger |  | FUNCTION |
| public.time_dist | interval | time without time zone, time without time zone | FUNCTION |
| public.ts_dist | interval | timestamp without time zone, timestamp without time zone | FUNCTION |
| public.tstz_dist | interval | timestamp with time zone, timestamp with time zone | FUNCTION |
| public.uuid_generate_v1 | uuid |  | FUNCTION |
| public.uuid_generate_v1mc | uuid |  | FUNCTION |
| public.uuid_generate_v3 | uuid | namespace uuid, name text | FUNCTION |
| public.uuid_generate_v4 | uuid |  | FUNCTION |
| public.uuid_generate_v5 | uuid | namespace uuid, name text | FUNCTION |
| public.uuid_nil | uuid |  | FUNCTION |
| public.uuid_ns_dns | uuid |  | FUNCTION |
| public.uuid_ns_oid | uuid |  | FUNCTION |
| public.uuid_ns_url | uuid |  | FUNCTION |
| public.uuid_ns_x500 | uuid |  | FUNCTION |

## Relations

```mermaid
erDiagram

"public.appointment_hours" }o--|| "public.appointment_settings" : "FOREIGN KEY (tenant_id) REFERENCES appointment_settings(tenant_id) ON DELETE CASCADE"
"public.appointment_notifications" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.appointment_notifications" }o--|| "public.appointments" : "FOREIGN KEY (tenant_id, appointment_id) REFERENCES appointments(tenant_id, id) ON DELETE RESTRICT"
"public.appointment_settings" |o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.appointments" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.appointments" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.care_relationships" }o--|| "public.user" : "FOREIGN KEY (practitioner_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.care_relationships" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.care_relationships" }o--|| "public.patients" : "FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE RESTRICT"
"public.care_relationships" }o--o| "public.clinics" : "FOREIGN KEY (clinic_id) REFERENCES clinics(id) ON DELETE RESTRICT"
"public.clinical_record_versions" }o--|| "public.user" : "FOREIGN KEY (author_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.clinical_record_versions" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.clinical_record_versions" }o--|| "public.clinical_records" : "FOREIGN KEY (tenant_id, clinical_record_id) REFERENCES clinical_records(tenant_id, id) ON DELETE RESTRICT"
"public.clinical_records" }o--|| "public.user" : "FOREIGN KEY (author_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.clinical_records" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.clinical_records" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.clinics" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.dispatch_attempts" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.dispatch_attempts" }o--|| "public.tga_approvals" : "FOREIGN KEY (tenant_id, approval_id) REFERENCES tga_approvals(tenant_id, id) ON DELETE RESTRICT"
"public.dispatch_attempts" }o--|| "public.prescriptions" : "FOREIGN KEY (tenant_id, prescription_id) REFERENCES prescriptions(tenant_id, id) ON DELETE RESTRICT"
"public.intake_applications" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.intake_applications" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.intake_applications" }o--|| "public.appointments" : "FOREIGN KEY (tenant_id, appointment_id) REFERENCES appointments(tenant_id, id) ON DELETE RESTRICT"
"public.intake_applications" }o--|| "public.pharmacies" : "FOREIGN KEY (tenant_id, pharmacy_id) REFERENCES pharmacies(tenant_id, id) ON DELETE RESTRICT"
"public.patient_alerts" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.patient_alerts" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.patient_consents" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.patient_consents" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.patient_consents" }o--o| "public.intake_applications" : "FOREIGN KEY (application_id) REFERENCES intake_applications(id) ON DELETE RESTRICT"
"public.patient_emergency_contacts" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.patient_emergency_contacts" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.patients" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.patients" }o--o| "public.patients" : "FOREIGN KEY (merged_into_patient_id) REFERENCES patients(id) ON DELETE RESTRICT"
"public.patients" }o--|| "public.pharmacies" : "FOREIGN KEY (tenant_id, preferred_pharmacy_id) REFERENCES pharmacies(tenant_id, id) ON DELETE RESTRICT"
"public.pharmacies" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.practitioner_agreements" }o--|| "public.user" : "FOREIGN KEY (attested_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.practitioner_agreements" }o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.practitioner_agreements" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.practitioner_identifiers" }o--|| "public.user" : "FOREIGN KEY (updated_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.practitioner_identifiers" }o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.practitioner_identifiers" }o--o| "public.user" : "FOREIGN KEY (verified_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.practitioner_identifiers" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.prescription_events" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.prescription_events" }o--|| "public.prescriptions" : "FOREIGN KEY (tenant_id, prescription_id) REFERENCES prescriptions(tenant_id, id) ON DELETE RESTRICT"
"public.prescriptions" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.prescriptions" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.prescriptions" }o--|| "public.tga_approvals" : "FOREIGN KEY (tenant_id, approval_id) REFERENCES tga_approvals(tenant_id, id) ON DELETE RESTRICT"
"public.prescriptions" }o--|| "public.prescriptions" : "FOREIGN KEY (tenant_id, supersedes_id) REFERENCES prescriptions(tenant_id, id) ON DELETE RESTRICT"
"public.role_permissions" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.role_permissions" }o--|| "public.permissions" : "FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE RESTRICT"
"public.role_permissions" }o--|| "public.roles" : "FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT"
"public.roles" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.sop_acknowledgements" }o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.sop_acknowledgements" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.sop_acknowledgements" }o--|| "public.sop_versions" : "FOREIGN KEY (tenant_id, sop_id, version) REFERENCES sop_versions(tenant_id, sop_id, version) ON DELETE RESTRICT"
"public.sop_versions" }o--|| "public.user" : "FOREIGN KEY (published_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.sop_versions" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.sop_versions" }o--|| "public.sops" : "FOREIGN KEY (tenant_id, sop_id) REFERENCES sops(tenant_id, id) ON DELETE RESTRICT"
"public.sops" }o--|| "public.user" : "FOREIGN KEY (created_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.sops" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.staff_invitations" }o--|| "public.user" : "FOREIGN KEY (invited_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.staff_invitations" |o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.staff_invitations" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.step_up_grants" }o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE CASCADE"
"public.step_up_grants" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE"
"public.tenant_settings" }o--|| "public.user" : "FOREIGN KEY (updated_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.tenant_settings" |o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.tga_approval_events" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.tga_approval_events" }o--|| "public.tga_approvals" : "FOREIGN KEY (tenant_id, approval_id) REFERENCES tga_approvals(tenant_id, id) ON DELETE RESTRICT"
"public.tga_approvals" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.tga_approvals" }o--|| "public.patients" : "FOREIGN KEY (tenant_id, patient_id) REFERENCES patients(tenant_id, id) ON DELETE RESTRICT"
"public.tga_approvals" }o--o| "public.tga_approvals" : "FOREIGN KEY (supersedes_id) REFERENCES tga_approvals(id) ON DELETE RESTRICT"
"public.user" }o--o| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL"
"public.user_roles" }o--|| "public.user" : "FOREIGN KEY (granted_by) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.user_roles" }o--|| "public.user" : "FOREIGN KEY (user_id) REFERENCES #quot;user#quot;(id) ON DELETE RESTRICT"
"public.user_roles" }o--|| "public.tenants" : "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE RESTRICT"
"public.user_roles" }o--|| "public.roles" : "FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT"

"public.appointment_hours" {
  time_without_time_zone closes_at
  time_without_time_zone opens_at
  uuid tenant_id FK
  smallint weekday
}
"public.appointment_notifications" {
  uuid appointment_id FK
  smallint attempts
  timestamp_with_time_zone claimed_at
  timestamp_with_time_zone created_at
  timestamp_with_time_zone due_at
  uuid id
  varchar kind
  varchar outcome
  timestamp_with_time_zone sent_at
  varchar status
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
}
"public.appointment_settings" {
  timestamp_with_time_zone created_at
  smallint slot_minutes
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
}
"public.appointments" {
  timestamp_with_time_zone created_at
  uuid created_by
  tstzrange during
  timestamp_with_time_zone ends_at
  uuid id
  uuid patient_id FK
  uuid practitioner_id
  varchar source
  timestamp_with_time_zone starts_at
  varchar status
  uuid tenant_id FK
  varchar type
  timestamp_with_time_zone updated_at
}
"public.audit_log" {
  varchar_128_ action
  uuid actor_id
  varchar_64_ actor_role
  varchar_128_ correlation_id
  uuid event_id
  varchar_64_ hash
  jsonb metadata
  varchar_64_ prev_hash
  varchar_255_ reason
  varchar_128_ request_id
  uuid resource_id
  varchar_32_ resource_type
  varchar_16_ result
  varchar_64_ source_ip
  uuid tenant_id
  timestamp_with_time_zone timestamp
}
"public.care_relationships" {
  timestamp_with_time_zone active_from
  timestamp_with_time_zone active_to
  uuid clinic_id FK
  timestamp_with_time_zone created_at
  uuid id
  uuid patient_id FK
  uuid practitioner_id FK
  varchar_128_ source
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
}
"public.clinical_record_versions" {
  uuid author_id FK
  varchar body
  varchar body_format
  uuid clinical_record_id FK
  timestamp_with_time_zone created_at
  uuid id
  varchar reason
  varchar signature_digest
  timestamp_with_time_zone signed_at
  integer supersedes_version
  uuid tenant_id FK
  integer version
}
"public.clinical_records" {
  uuid author_id FK
  timestamp_with_time_zone created_at
  integer current_version
  timestamp_with_time_zone deleted_at
  uuid id
  uuid patient_id FK
  varchar record_type
  timestamp_with_time_zone signed_at
  uuid tenant_id FK
}
"public.clinics" {
  varchar_255_ address
  timestamp_with_time_zone created_at
  uuid id
  varchar_255_ name
  varchar_64_ phone
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
}
"public.dispatch_attempts" {
  uuid approval_id FK
  integer attempt_seq
  timestamp_with_time_zone claimed_at
  varchar error_class
  uuid id
  varchar idempotency_key
  integer latency_ms
  varchar outcome_class
  uuid prescription_id FK
  varchar provider
  varchar provider_reference
  varchar request_payload_hash
  timestamp_with_time_zone requested_at
  uuid requested_by
  varchar resolution_reason
  timestamp_with_time_zone resolved_at
  varchar state
  uuid tenant_id FK
}
"public.intake_applications" {
  jsonb answers
  uuid appointment_id FK
  jsonb consents
  timestamp_with_time_zone created_at
  boolean created_patient
  timestamp_with_time_zone decided_at
  uuid decided_by
  varchar_500_ decision_note
  varchar decision_reason_code
  varchar_255_ declaration_name
  timestamp_with_time_zone declared_at
  text__ flags
  uuid id
  jsonb own_pharmacy
  uuid patient_id FK
  uuid pharmacy_id FK
  varchar status
  uuid tenant_id FK
}
"public.patient_alerts" {
  timestamp_with_time_zone created_at
  uuid created_by
  uuid id
  uuid patient_id FK
  timestamp_with_time_zone removed_at
  uuid removed_by
  uuid tenant_id FK
  varchar_120_ text
  varchar tone
}
"public.patient_consents" {
  uuid application_id FK
  timestamp_with_time_zone created_at
  uuid id
  varchar kind
  varchar method
  uuid patient_id FK
  uuid recorded_by
  timestamp_with_time_zone signed_at
  uuid tenant_id FK
  varchar_64_ text_sha256
  varchar_32_ version
}
"public.patient_emergency_contacts" {
  timestamp_with_time_zone created_at
  uuid created_by
  uuid id
  varchar_255_ name
  uuid patient_id FK
  varchar_64_ phone
  varchar_100_ relationship
  timestamp_with_time_zone removed_at
  uuid removed_by
  uuid tenant_id FK
}
"public.patients" {
  varchar address_line
  timestamp_with_time_zone created_at
  date date_of_birth
  timestamp_with_time_zone deceased_at
  timestamp_with_time_zone deleted_at
  varchar email
  varchar family_name
  varchar gender_identity
  varchar given_name
  uuid id
  bytea ihi
  bytea ihi_blind_index
  bytea medicare_blind_index
  smallint medicare_irn
  bytea medicare_number
  uuid merged_into_patient_id FK
  varchar phone
  varchar postcode
  varchar preferred_name
  uuid preferred_pharmacy_id FK
  boolean receives_communications
  varchar sex_at_birth
  varchar state
  varchar status
  timestamp_with_time_zone status_changed_at
  varchar_500_ status_reason
  varchar suburb
  uuid tenant_id FK
  varchar_64_ timezone
  timestamp_with_time_zone updated_at
}
"public.permissions" {
  varchar code
  varchar description
  uuid id
}
"public.pharmacies" {
  varchar_255_ address
  timestamp_with_time_zone created_at
  varchar created_from
  varchar_255_ email
  uuid id
  boolean is_partner
  varchar_255_ name
  varchar_64_ phone
  varchar_32_ provider_number
  varchar_255_ suburb
  uuid tenant_id FK
}
"public.practitioner_agreements" {
  varchar_32_ agreement_version
  timestamp_with_time_zone attested_at
  uuid attested_by FK
  uuid id
  date signed_on
  uuid tenant_id FK
  uuid user_id FK
}
"public.practitioner_identifiers" {
  date expires_on
  uuid id
  varchar kind
  varchar status
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
  uuid updated_by FK
  uuid user_id FK
  bytea value_ciphertext
  varchar_120_ verification_method
  timestamp_with_time_zone verified_at
  uuid verified_by FK
}
"public.prescription_events" {
  uuid actor_id
  varchar from_state
  uuid id
  timestamp_with_time_zone occurred_at
  uuid prescription_id FK
  varchar reason
  uuid tenant_id FK
  varchar to_state
}
"public.prescriptions" {
  varchar_64_ addendum_key
  uuid approval_id FK
  varchar_64_ cancel_reason_code
  varchar conventional_therapy
  timestamp_with_time_zone created_at
  date date_of_service
  varchar dosage_form
  varchar dose_instruction
  uuid drafted_by
  uuid id
  varchar medicine_name
  uuid patient_id FK
  varchar payload_hash
  uuid prescriber_id
  numeric_10_2_ quantity
  smallint repeats
  timestamp_with_time_zone signed_at
  uuid signed_by
  varchar state
  uuid supersedes_id FK
  uuid tenant_id FK
  varchar tga_category
  varchar triage_outcome
  timestamp_with_time_zone updated_at
}
"public.role_permissions" {
  uuid permission_id FK
  uuid role_id FK
  uuid tenant_id FK
}
"public.roles" {
  varchar code
  timestamp_with_time_zone created_at
  uuid id
  boolean is_system
  varchar name
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
}
"public.signup_requests" {
  varchar_255_ clinic_name
  timestamp_with_time_zone created_at
  varchar_255_ email
  varchar_255_ email_key
  timestamp_with_time_zone expires_at
  varchar_255_ full_name
  varchar hashed_password
  uuid id
  uuid link_id
  integer send_count
  timestamp_with_time_zone sent_at
}
"public.sop_acknowledgements" {
  timestamp_with_time_zone acknowledged_at
  uuid id
  uuid sop_id FK
  uuid tenant_id FK
  uuid user_id FK
  integer version FK
}
"public.sop_versions" {
  text body
  uuid id
  timestamp_with_time_zone published_at
  uuid published_by FK
  uuid sop_id FK
  uuid tenant_id FK
  varchar_200_ title
  integer version
}
"public.sops" {
  text__ applies_to_roles
  timestamp_with_time_zone created_at
  uuid created_by FK
  integer current_version
  uuid id
  boolean required_for_onboarding
  uuid tenant_id FK
  varchar_200_ title
  timestamp_with_time_zone updated_at
}
"public.staff_invitations" {
  timestamp_with_time_zone accepted_at
  timestamp_with_time_zone created_at
  timestamp_with_time_zone expires_at
  uuid invited_by FK
  varchar_64_ pending_password_digest
  timestamp_with_time_zone sent_at
  uuid tenant_id FK
  uuid user_id FK
}
"public.step_up_grants" {
  timestamp_with_time_zone consumed_at
  timestamp_with_time_zone expires_at
  uuid id
  timestamp_with_time_zone issued_at
  varchar operation
  uuid resource_id
  uuid tenant_id FK
  varchar token_hash
  uuid user_id FK
}
"public.tenant_settings" {
  integer adult_retention_years
  uuid tenant_id FK
  timestamp_with_time_zone updated_at
  uuid updated_by FK
}
"public.tenants" {
  timestamp_with_time_zone created_at
  varchar_32_ data_region
  varchar_120_ display_name
  uuid id
  varchar_255_ legal_name
  varchar_64_ retention_profile
  varchar_64_ slug
  varchar_16_ status
  timestamp_with_time_zone updated_at
}
"public.tga_approval_events" {
  uuid actor_id
  uuid approval_id FK
  varchar from_state
  uuid id
  timestamp_with_time_zone occurred_at
  varchar reason
  varchar source
  uuid tenant_id FK
  varchar to_state
}
"public.tga_approvals" {
  varchar approval_reference
  timestamp_with_time_zone created_at
  uuid created_by
  varchar creation_reason
  varchar dosage_form
  uuid id
  uuid patient_id FK
  timestamp_with_time_zone revoked_at
  uuid revoked_by
  varchar revoked_reason_code
  varchar source
  uuid source_document_id
  varchar state
  uuid superseded_by_id
  uuid supersedes_id FK
  uuid tenant_id FK
  varchar tga_category
  timestamp_with_time_zone updated_at
  date valid_from
  date valid_to
  daterange validity_interval
  timestamp_with_time_zone verified_at
  uuid verified_by
}
"public.user" {
  timestamp_with_time_zone created_at
  varchar_255_ email
  varchar_255_ full_name
  varchar hashed_password
  uuid id
  boolean is_active
  boolean is_superuser
  uuid tenant_id FK
}
"public.user_roles" {
  timestamp_with_time_zone granted_at
  uuid granted_by FK
  timestamp_with_time_zone last_reviewed_at
  uuid role_id FK
  uuid tenant_id FK
  uuid user_id FK
}
```

---

> Generated by [tbls](https://github.com/k1LoW/tbls)
