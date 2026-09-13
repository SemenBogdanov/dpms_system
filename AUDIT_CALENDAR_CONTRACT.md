# Audit Calendar V5: Local Integration Contract

Local candidate only; no production rollout or real source import is authorized.
Baseline: e46e8bbbc83be89c930df457431d737bcee40a73. Primary spec is the PersonalOS
Audit Calendar Project Session Prompt 2026-09-11, not this implementation sketch.

## Approved Policy

- One explicit calendar scope, Europe/Moscow, Monday-Friday without holidays.
- Existing User IDs, separate User.audit_calendar_enabled boolean (default false).
- Active calendar membership required to read data. System admin does not bypass
  calendar read/write guards; admin can explicitly grant membership/helper to self.
- Scope membership: user_id, code, role (auditor/tech/speaker/observer), can_manage,
  active. Helper is a scope capability, not inherited from admin/teamlead/audit leader.
- Admin manages scope setup and membership through admin-only endpoints, without
  automatically gaining access to meetings/facts/availability.
- Independent calendar absence history, no implicit Q/UserAbsence/GlobalHoliday sync.
- V5 unknown availability: a day with no free windows allows a warning unless
  a busy window overlaps. Once free windows exist on that day, the entire meeting
  must fit their union. Absence and overlapping busy always block.
- No case/contract auto-linking, no Q effects, messages, email or AI calls.

## Ownership

Backend worker owns new calendar models/schema/service/router/migration/tests only.
Frontend worker owns AuditCalendarPage, components/audit-calendar/*,
api/auditCalendar.ts, page-local styling and browser tests only.
Main integrator owns User model/schema/routes/audit, main.py/models init,
App/UserModal/AdminUsersPage, access/types/navigation/menu and shared regression gates.
Never edit old AuditPage or prototype, .env*, credential files, unrelated worktrees.

## API

Prefix /api/audit-calendar. Server resolves actor and all permissions, never URL actor.
All writes include request_id UUID and expected_version integer. Scope version is
monotonic. Replay with same key/body returns prior result; different body is 409.
Recheck current permissions BEFORE replay. Mutation response: {version, result}.
Errors use FastAPI detail (string or structured field errors); stale is 409 and
must preserve browser draft. State refresh occurs only after confirmed success.

### Admin Setup

- GET /admin -> {scope: Scope|null, members: Member[], users: {id,full_name,email,audit_calendar_enabled,is_active}[]}
- POST /admin/setup {request_id,name,baseline} -> {version,result}; singleton scope;
  setup is explicit, default baseline server today, initial team norm6 at baseline.
- POST /admin/members {request_id,expected_version,user_id,code,role,can_manage,active}
  -> {version,result}. User needs explicit section grant before active membership.
  This does not change the section grant itself. New/updated membership is audited.

### State

GET /state?from=YYYY-MM-DD&to=YYYY-MM-DD[&group=UUID&person=UUID&q=text]
returns:

```ts
type Scope = {id:string; name:string; timezone:string; baseline:string;
  version:number; today:string; now:string; archived:boolean; history_complete:boolean}
type Member = {user_id:string; full_name:string; code:string;
  role:'auditor'|'tech'|'speaker'|'observer'; can_manage:boolean; active:boolean}
type GroupVersion = {id:string; effective_from:string; auditor_id:string|null; tech_id:string|null}
type Group = {id:string; code:string; label:string; legacy:boolean; archived:boolean; versions:GroupVersion[]}
type Issue = {code:string; message:string}
type Plan = {id:string; date:string; start:number; duration:number; group_id:string;
  group_version_id:string|null; activity:string; speaker_id:string|null;
  status:'draft'|'planned'|'cancelled'; version:number; origin:string;
  source_id:string|null; issues:Issue[]; warnings:Issue[]}
type Fact = {id:string; plan_id:string|null; date:string; start:number; duration:number;
  group_id:string|null; activity:string; speaker_id:string|null;
  outcome:'completed'|'cancelled'; reason:string; evidence:string;
  recorded_by_id:string; recorded_at:string; participant_snapshot:unknown[];
  planned_snapshot:unknown|null; composition_unknown:boolean; origin:string}
type Availability = {user_id:string; date:string; start:number; end:number; available:boolean}
type Absence = {id:string; user_id:string; start_date:string; end_date:string;
  reason:string; version:number; status:'active'|'cancelled'}
type Norm = {id:string; group_id:string|null; effective_from:string; value:number;
  reason:string; recorded_at:string; recorded_by_id:string}
type Notice = {id:string; plan_id:string; user_id:string; reported_at:string; reason:string}
type Totals = {target:number; completed:number; balance:number; backlog:number}
type Stats = {plan:number; fact:number; attention:number; target:number; backlog:number;
  through:string|null; target_scope:string; daily_targets:Record<string,number>;
  groups:({group_id:string; code:string}&Totals)[];
  fortnights:({from:string; to:string; cumulative_backlog:number}&Totals)[]}
type State = {scope:Scope; actor:{user_id:string; can_manage:boolean}; members:Member[];
  groups:Group[]; plans:Plan[]; facts:Fact[]; availability:Availability[];
  absences:Absence[]; norms:Norm[]; notices:Notice[]; stats:Stats}
```

State collections are scoped and period bounded except small directories/norms.
Server stats use ALL history from baseline, not only facts on the visible page.
Filters affect meeting counts, group affects targets, person/search do not affect
target or accumulated backlog. Archived groups retain historical norms.

### Typed Commands

POST /commands {request_id,expected_version,operation,payload} with a strict
Pydantic-validated payload per operation (unknown fields rejected):

- group.save {id?:UUID,code,label,legacy?:false,archived?:boolean,
  effective_from:date,auditor_id?:UUID,tech_id?:UUID,reason:string}
- plan.save {id?:UUID,date,start,duration,group_id,activity,speaker_id,
  status:draft|planned|cancelled,reason?:string}
- plan.revise {id:UUID,date,start,duration,group_id,activity,speaker_id,
  status:draft|planned|cancelled,reason:string} // explicit source working revision
- fact.record {plan_id:UUID,date,start,duration,group_id,activity,speaker_id,
  outcome:completed|cancelled,reason:string,evidence:string,auditor_absent_minutes:int}
- notice.record {plan_id,user_id,reported_at:aware datetime,reason:string}
- availability.paint {user_id,patches:[{date,start,end,value:boolean|null}]}
- absence.add {user_id,start_date,end_date,reason}
- absence.end {id,reason} // cancel future or truncate today onward, retain past
- norm.set {group_id:UUID|null,effective_from,value:int,reason}
- scope.archive {archived:boolean,reason} // helper, preserves all history

Membership edits are admin-only. Other management commands helper-only.
Availability/absence employee writes require own user_id, helper can affect members.
Fact corrections/deletion and norm historical rewrites have NO command.
Past plan edits become working revisions only through the source workflow, never
silently confer legacy eligibility. Fact and associated frozen plan cannot edit.

### Import

GET /imports -> batches visible to helper only.
POST /imports/preview {request_id,expected_version,source:V5JSON,mapping:{sourcePersonId:userUUID},
bootstrap_history?:boolean,group_mapping?:{groupCode:{auditor_id:UUID,tech_id:UUID}}}
returns {id,version,status,summary,issues,rows,mapping_required,source_sha256}.
V5 source schema is validated, original retained, references bound to scope and batch.
No last-write-wins. Older JSON without planning leaves current norms/absences intact.
POST /imports/{id}/apply {request_id,expected_version,confirm:true,reason}
revalidates under lock, append-only application, event and immutable mapping revision.
Unverified upload is not proof for historical exemption; helper explicit confirmation
records accepted source/horizon/mapping. No batch auto-import on page load/migration.
Historical fact restoring a source plan uses a dedicated typed operation
fact.restore {source_row_id,date,start,duration,activity,speaker_id,outcome,reason,
evidence,composition_unknown,participants:[{user_id,role}],confirm:true}.
Historical group attribution stays bound to source, actual date within source
horizon and before today. Original standalone source fact remains without plan_id.
Canonical source identity spans repeat export batches: another exportedAt/batch
does not create another fact or another opportunity to restore the same source.
Explicit history bootstrap only applies to an empty calendar with its initial
setup norm and matching preconfigured baseline. It can append confirmed historical
norms and explicitly mapped modern groups; it cannot invent a G21 composition/quota
or rewrite existing history. Imported availability/absences are checked together
with incoming plans before committing the batch.

GET /history?limit=100 returns {items:[{id,action,actor_name,occurred_at,detail}],total}.
No existing audit_case/atom changes. Dataset CSV export can be browser-built only
from authorized state or a guarded server export; no export of hidden scope.

## Persistence And Verification

Normalized tables for scope/member/group/group_version/plan/participant/fact,
availability/absence/norm_revision/notice/event/import_batch/import_row/idempotency.
JSON only for immutable original/snapshots and bounded validation summaries.
Single stable scope row lock serializes short mutation transactions; re-read after
lock. User lock order is deterministic for current actor/old+new participants so
concurrent revocation is respected. Import parsing/model work never runs under lock.
Postgres triggers/constraints protect facts and children, original/import evidence,
historical norms and events from updates/deletes/cascade. Downgrade refuses data loss.
Fresh and086->new migrations tested on disposable PostgreSQL, no current local DB.

Helper UI: central protected modal on plan cell; no global New Meeting action.
Local navigation bottom-left in own area, no global Sidebar changes except menu item.
Themes use DPMS tokens, mobile daily Time/Plan/Fact, URL view/period/filter state.
Screenshots and tests cover roles/themes/widths from primary spec.

Actual candidate acceptance is separate from this contract and prototype tests.
