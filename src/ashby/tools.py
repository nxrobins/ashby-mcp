"""Tool schema definitions — the full list exposed to MCP clients.

Every tool is classified in `_HINTS` below (read-only / destructive /
idempotent). The classification is published to clients as MCP tool
annotations, so a client can confirm before running a write, and it
drives the ASHBY_READ_ONLY policy, so there is no second list to keep in
sync. A tool without an entry fails at import instead of shipping
unclassified. `all_tools()` applies the runtime policy in policy.py.
"""

from dataclasses import dataclass

import mcp.types as types

from . import policy


@dataclass(frozen=True)
class Hints:
    """MCP tool annotations (readOnlyHint / destructiveHint / idempotentHint)."""

    read_only: bool
    destructive: bool
    idempotent: bool


READ_ONLY = Hints(read_only=True, destructive=False, idempotent=True)
# Writes, by effect. "Destructive" follows the MCP spec: the call may
# overwrite or remove existing data, as opposed to only adding to it.
ADDITIVE = Hints(
    read_only=False, destructive=False, idempotent=False
)  # creates a new record each call
ADDITIVE_IDEMPOTENT = Hints(
    read_only=False, destructive=False, idempotent=True
)  # attaches; repeating is a no-op
DESTRUCTIVE = Hints(
    read_only=False, destructive=True, idempotent=False
)  # overwrites; repeating adds more
DESTRUCTIVE_IDEMPOTENT = Hints(
    read_only=False, destructive=True, idempotent=True
)  # overwrites/removes; repeating is a no-op

_HINTS: dict[str, Hints] = {
    # Candidates
    "create_candidate": ADDITIVE,
    "search_candidates": READ_ONLY,
    "list_candidates": READ_ONLY,
    "list_all_candidates": READ_ONLY,
    "get_candidate": READ_ONLY,
    "update_candidate": DESTRUCTIVE_IDEMPOTENT,
    "add_candidate_tag": ADDITIVE_IDEMPOTENT,
    "list_candidate_tags": READ_ONLY,
    "add_candidate_to_project": ADDITIVE_IDEMPOTENT,
    "create_candidate_note": ADDITIVE,
    "list_candidate_notes": READ_ONLY,
    "list_candidate_client_info": READ_ONLY,
    "anonymize_candidate": DESTRUCTIVE_IDEMPOTENT,  # irreversible
    "upload_candidate_resume": DESTRUCTIVE,  # replaces the primary resume
    "upload_candidate_file": ADDITIVE,
    # Projects
    "get_project": READ_ONLY,
    "list_projects": READ_ONLY,
    "search_projects": READ_ONLY,
    # Custom fields
    "list_custom_fields": READ_ONLY,
    "get_custom_field": READ_ONLY,
    "create_custom_field": ADDITIVE,
    "set_custom_field_value": DESTRUCTIVE_IDEMPOTENT,
    # Jobs
    "create_job": ADDITIVE,
    "search_jobs": READ_ONLY,
    "list_jobs": READ_ONLY,
    "get_job": READ_ONLY,
    "update_job": DESTRUCTIVE_IDEMPOTENT,
    "set_job_status": DESTRUCTIVE_IDEMPOTENT,
    # Applications
    "create_application": ADDITIVE,
    "list_applications": READ_ONLY,
    "get_application": READ_ONLY,
    "update_application": DESTRUCTIVE_IDEMPOTENT,
    "change_application_stage": DESTRUCTIVE_IDEMPOTENT,
    "change_application_source": DESTRUCTIVE_IDEMPOTENT,
    "transfer_application": DESTRUCTIVE_IDEMPOTENT,
    "add_application_hiring_team_member": ADDITIVE_IDEMPOTENT,
    "remove_application_hiring_team_member": DESTRUCTIVE_IDEMPOTENT,
    # Interviews
    "get_interview": READ_ONLY,
    "list_interviews": READ_ONLY,
    "create_interview_schedule": ADDITIVE,
    "list_interview_schedules": READ_ONLY,
    "update_interview_schedule": DESTRUCTIVE,  # creates a new event when no interviewEventId is given
    "cancel_interview_schedule": DESTRUCTIVE_IDEMPOTENT,
    "list_interview_events": READ_ONLY,
    "list_interview_plans": READ_ONLY,
    "list_interview_stages": READ_ONLY,
    "get_interview_stage": READ_ONLY,
    "list_interview_stage_groups": READ_ONLY,
    "list_sources": READ_ONLY,
    "list_application_feedback": READ_ONLY,
}

# Tools that open a file on the machine running the server. See
# policy.uploads_enabled() for why these are off by default over HTTP.
LOCAL_FILE_TOOLS = frozenset({"upload_candidate_resume", "upload_candidate_file"})


def _annotations(hints: Hints):
    """Build the `annotations` value for a Tool on whatever mcp is installed.

    `mcp.types.ToolAnnotations` exists from mcp 1.6. Older releases (the
    lockfile pins 1.1.2) have no such field, but every mcp type allows
    extras, so a plain dict is stored and serialised verbatim in
    tools/list — which is exactly the wire format.
    """
    fields = {
        "readOnlyHint": hints.read_only,
        "destructiveHint": hints.destructive,
        "idempotentHint": hints.idempotent,
    }
    typed = getattr(types, "ToolAnnotations", None)
    return typed(**fields) if typed is not None else fields


def _tool(*, name: str, description: str, inputSchema: dict) -> types.Tool:
    """A types.Tool carrying the annotations from `_HINTS`.

    KeyError here means a new tool was added without classifying it —
    add it to `_HINTS` (which is what ASHBY_READ_ONLY keys off).
    """
    return types.Tool(
        name=name,
        description=description,
        inputSchema=inputSchema,
        annotations=_annotations(_HINTS[name]),
    )


def _catalog() -> list[types.Tool]:
    """Every Ashby MCP tool, with their JSON-schema inputs, before policy."""
    return [
        # Candidate Management Tools
        _tool(
            name="create_candidate",
            description="Create a new candidate in Ashby. Only `name` is required; other fields are optional but useful.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Full name"},
                    "email": {"type": "string", "description": "Primary email"},
                    "phoneNumber": {"type": "string", "description": "Primary phone number"},
                    "linkedInUrl": {"type": "string", "description": "LinkedIn profile URL"},
                    "githubUrl": {"type": "string", "description": "GitHub profile URL"},
                    "website": {"type": "string", "description": "Personal website URL"},
                    "alternateEmailAddresses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional email addresses",
                    },
                    "sourceId": {
                        "type": "string",
                        "description": "ID of the source to attribute the candidate to",
                    },
                    "creditedToUserId": {
                        "type": "string",
                        "description": "ID of the user the candidate is credited to",
                    },
                    "location": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "region": {"type": "string"},
                            "country": {"type": "string"},
                        },
                        "description": "Candidate's location",
                    },
                    "createdAt": {
                        "type": "string",
                        "description": "ISO 8601 override for createdAt",
                    },
                },
                "required": ["name"],
            },
        ),
        _tool(
            name="search_candidates",
            description="Search for candidates by email and/or name",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Candidate's email"},
                    "name": {"type": "string", "description": "Candidate's name"},
                },
            },
        ),
        _tool(
            name="list_candidates",
            description="List candidates. Uses Ashby's cursor-based pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cursor": {
                        "type": "string",
                        "description": "Opaque pagination cursor returned by a prior call",
                    },
                    "syncToken": {
                        "type": "string",
                        "description": "Token from a previous full sync — returns only changes since",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results per page (1-100, default 100)",
                    },
                },
            },
        ),
        _tool(
            name="list_all_candidates",
            description=(
                "Fetch candidates by auto-paginating /candidate.list, up to 50 pages "
                "(5,000 candidates) in one call. If the workspace has more than that, "
                "the response is marked `truncated: true` and includes `nextCursor` — "
                "continue with list_candidates from that cursor. Use list_candidates "
                "directly when you only need a single page."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "syncToken": {
                        "type": "string",
                        "description": "Optional sync token for incremental fetch — returns only candidates changed since the token was issued",
                    }
                },
            },
        ),
        _tool(
            name="get_candidate",
            description="Fetch a single candidate by ID (full record including custom fields, applications, etc.)",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Candidate ID"}},
                "required": ["id"],
            },
        ),
        _tool(
            name="update_candidate",
            description="Update an existing candidate's fields. Only send fields you want to change.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string", "description": "Candidate ID to update"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phoneNumber": {"type": "string"},
                    "linkedInUrl": {"type": "string"},
                    "githubUrl": {"type": "string"},
                    "websiteUrl": {"type": "string"},
                    "alternateEmail": {
                        "type": "string",
                        "description": "Alternate email address to add to the candidate's profile",
                    },
                    "sourceId": {"type": "string"},
                    "creditedToUserId": {"type": "string"},
                    "location": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "region": {"type": "string"},
                            "country": {"type": "string"},
                        },
                    },
                    "socialLinks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"type": {"type": "string"}, "url": {"type": "string"}},
                        },
                        "description": "Replaces existing socialLinks. If sent, linkedInUrl/githubUrl/websiteUrl are ignored.",
                    },
                    "createdAt": {"type": "string", "description": "ISO 8601 date override"},
                },
                "required": ["candidateId"],
            },
        ),
        _tool(
            name="add_candidate_tag",
            description="Attach a tag to a candidate. Use list_candidate_tags to discover tagId.",
            inputSchema={
                "type": "object",
                "properties": {"candidateId": {"type": "string"}, "tagId": {"type": "string"}},
                "required": ["candidateId", "tagId"],
            },
        ),
        _tool(
            name="list_candidate_tags",
            description="List all candidate tags available in the Ashby workspace (for discovering tagId).",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {
                        "type": "boolean",
                        "description": "Include archived tags (default false)",
                    },
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        _tool(
            name="add_candidate_to_project",
            description="Attach a candidate to a project.",
            inputSchema={
                "type": "object",
                "properties": {"candidateId": {"type": "string"}, "projectId": {"type": "string"}},
                "required": ["candidateId", "projectId"],
            },
        ),
        _tool(
            name="create_candidate_note",
            description="Add a note to a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "note": {"type": "string", "description": "Note text"},
                    "createdAt": {"type": "string", "description": "ISO 8601 timestamp override"},
                },
                "required": ["candidateId", "note"],
            },
        ),
        _tool(
            name="list_candidate_notes",
            description="List notes attached to a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["candidateId"],
            },
        ),
        _tool(
            name="list_candidate_client_info",
            description="List client info records (e.g. agency submissions) for a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["candidateId"],
            },
        ),
        _tool(
            name="anonymize_candidate",
            description="Anonymize a candidate (GDPR / data retention). Irreversible.",
            inputSchema={
                "type": "object",
                "properties": {"candidateId": {"type": "string"}},
                "required": ["candidateId"],
            },
        ),
        _tool(
            name="upload_candidate_resume",
            description="Upload a resume to a candidate. `file_path` must be a path on the machine running this MCP server.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "file_path": {
                        "type": "string",
                        "description": "Absolute local path to the resume file (PDF, docx, etc.)",
                    },
                },
                "required": ["candidateId", "file_path"],
            },
        ),
        _tool(
            name="upload_candidate_file",
            description="Upload an arbitrary file to a candidate. `file_path` must be a path on the machine running this MCP server.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "file_path": {
                        "type": "string",
                        "description": "Absolute local path to the file",
                    },
                },
                "required": ["candidateId", "file_path"],
            },
        ),
        # Project Tools
        _tool(
            name="get_project",
            description="Fetch a single project by id (returns title, archived state, associated jobs, etc.).",
            inputSchema={
                "type": "object",
                "properties": {"projectId": {"type": "string"}},
                "required": ["projectId"],
            },
        ),
        _tool(
            name="list_projects",
            description="List all projects with cursor-based pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cursor": {"type": "string", "description": "Opaque pagination cursor"},
                    "syncToken": {
                        "type": "string",
                        "description": "Token from a previous full sync — returns only changes since",
                    },
                    "limit": {"type": "integer", "description": "Max results (1-100, default 100)"},
                },
            },
        ),
        _tool(
            name="search_projects",
            description="Search projects by title (required). Capped at 100 results — use list_projects with pagination to scan everything.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Project title to search for"}
                },
                "required": ["title"],
            },
        ),
        # Custom Field Tools
        _tool(
            name="list_custom_fields",
            description="List all custom fields defined in the workspace. Use the optional `objectType` arg to filter client-side (e.g. only Candidate fields for referral data). Returns field id, title, fieldType, and selectableValues you'll need for set_custom_field_value.",
            inputSchema={
                "type": "object",
                "properties": {
                    "objectType": {
                        "type": "string",
                        "enum": [
                            "Application",
                            "Candidate",
                            "Job",
                            "Employee",
                            "Talent_Project",
                            "Opening_Version",
                            "Offer_Version",
                        ],
                        "description": "Client-side filter — only return fields attached to this object type",
                    },
                    "includeArchived": {
                        "type": "boolean",
                        "description": "Include archived fields (default false)",
                    },
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        _tool(
            name="get_custom_field",
            description="Fetch a single custom field definition by id.",
            inputSchema={
                "type": "object",
                "properties": {"customFieldId": {"type": "string"}},
                "required": ["customFieldId"],
            },
        ),
        _tool(
            name="create_custom_field",
            description="Create a new custom field definition. Rare/admin operation — requires hiringProcessMetadataWrite permission.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "fieldType": {
                        "type": "string",
                        "enum": [
                            "Boolean",
                            "CompensationRange",
                            "Date",
                            "LongText",
                            "MultiValueSelect",
                            "Number",
                            "NumberRange",
                            "String",
                            "ValueSelect",
                        ],
                    },
                    "objectType": {
                        "type": "string",
                        "enum": [
                            "Application",
                            "Candidate",
                            "Job",
                            "Employee",
                            "Talent_Project",
                            "Opening_Version",
                            "Offer_Version",
                        ],
                    },
                    "description": {"type": "string"},
                    "selectableValues": {
                        "type": "array",
                        "description": "Required for ValueSelect/MultiValueSelect. Array of { label, value } objects.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["label", "value"],
                        },
                    },
                    "isDateOnlyField": {
                        "type": "boolean",
                        "description": "Date fields only — whether the field has no time component",
                    },
                    "isExposableToCandidate": {
                        "type": "boolean",
                        "description": "Must be true for the field to be usable in email templates (default false)",
                    },
                },
                "required": ["title", "fieldType", "objectType"],
            },
        ),
        _tool(
            name="set_custom_field_value",
            description=(
                "Set a custom field's value on a specific object (Candidate, Application, Job, or Opening). "
                "The shape of `fieldValue` depends on the field's fieldType:\n"
                "  Boolean → true/false\n"
                "  Date → ISO date-time string\n"
                "  String / LongText / Email / Phone → string\n"
                "  Number → number\n"
                "  ValueSelect → string matching one of the field's allowed values\n"
                "  MultiValueSelect → array of allowed-value strings\n"
                '  NumberRange → { "type": "number-range", "minValue": N, "maxValue": N }\n'
                "Use list_custom_fields first to discover fieldId and the allowed value set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "objectId": {
                        "type": "string",
                        "description": "ID of the Candidate / Application / Job / Opening",
                    },
                    "objectType": {
                        "type": "string",
                        "enum": ["Application", "Candidate", "Job", "Opening"],
                    },
                    "fieldId": {
                        "type": "string",
                        "description": "Custom field definition id (from list_custom_fields)",
                    },
                    "fieldValue": {
                        "description": "Value to store. Type depends on fieldType — see tool description.",
                        "oneOf": [
                            {"type": "boolean"},
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "array", "items": {"type": "string"}},
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "minValue": {"type": "number"},
                                    "maxValue": {"type": "number"},
                                },
                            },
                        ],
                    },
                },
                "required": ["objectId", "objectType", "fieldId", "fieldValue"],
            },
        ),
        # Job Management Tools
        _tool(
            name="create_job",
            description=(
                "Create a new job. Ashby requires `title`, `teamId`, and `locationId` — "
                "the call fails without all three. Use list_interview_plans to discover a "
                "`defaultInterviewPlanId` (needed before the job can be opened). Team and "
                "location IDs come from the Ashby UI or an existing job (get_job); this "
                "server does not expose department/location listing endpoints."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Job title"},
                    "teamId": {
                        "type": "string",
                        "description": "Department/team id (required by Ashby)",
                    },
                    "locationId": {
                        "type": "string",
                        "description": "Primary location id (required by Ashby)",
                    },
                    "defaultInterviewPlanId": {
                        "type": "string",
                        "description": "Required for the job to be opened",
                    },
                    "jobTemplateId": {
                        "type": "string",
                        "description": "Id of an active job template",
                    },
                    "brandId": {"type": "string"},
                },
                "required": ["title", "teamId", "locationId"],
            },
        ),
        _tool(
            name="search_jobs",
            description=(
                "Search jobs by title. `title` is the only filter Ashby's /job.search "
                "accepts — use list_jobs to enumerate or filter by status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Job title to search for"}
                },
                "required": ["title"],
            },
        ),
        _tool(
            name="list_jobs",
            description="List all jobs, optionally filtered by status (Open, Closed, Archived, Draft). Defaults to Open jobs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["Draft", "Open", "Closed", "Archived"],
                        },
                        "description": 'Statuses to include. Defaults to ["Open"].',
                    },
                    "openedAfter": {
                        "type": "integer",
                        "description": "Return jobs opened after this unix epoch millis timestamp",
                    },
                    "openedBefore": {
                        "type": "integer",
                        "description": "Return jobs opened before this unix epoch millis timestamp",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor from a previous response",
                    },
                    "limit": {"type": "integer", "description": "Max results per page"},
                },
            },
        ),
        _tool(
            name="get_job",
            description="Fetch a single job by id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Job id"},
                    "includeUnpublishedJobPostingsIds": {"type": "boolean"},
                    "expand": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["location", "openings"]},
                        "description": "Optional related objects to expand",
                    },
                },
                "required": ["id"],
            },
        ),
        _tool(
            name="update_job",
            description="Update a job's metadata (title, team, location, interview plan, etc.). Use set_job_status to change open/closed/archived state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "jobId": {"type": "string"},
                    "title": {"type": "string"},
                    "teamId": {"type": "string"},
                    "locationId": {"type": "string"},
                    "defaultInterviewPlanId": {"type": "string"},
                    "customRequisitionId": {"type": "string"},
                },
                "required": ["jobId"],
            },
        ),
        _tool(
            name="set_job_status",
            description="Change a job's status (Draft, Open, Closed, Archived).",
            inputSchema={
                "type": "object",
                "properties": {
                    "jobId": {"type": "string"},
                    "status": {"type": "string", "enum": ["Draft", "Open", "Closed", "Archived"]},
                },
                "required": ["jobId", "status"],
            },
        ),
        # Application Management Tools
        _tool(
            name="create_application",
            description="Create a new application — consider a candidate for a job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "jobId": {"type": "string"},
                    "interviewPlanId": {
                        "type": "string",
                        "description": "Defaults to the job's default plan",
                    },
                    "interviewStageId": {
                        "type": "string",
                        "description": "Stage within the plan; 'FirstPreInterviewScreen' is a special accepted value",
                    },
                    "sourceId": {"type": "string", "description": "Source attribution"},
                    "creditedToUserId": {"type": "string"},
                    "createdAt": {"type": "string", "description": "ISO date override"},
                },
                "required": ["candidateId", "jobId"],
            },
        ),
        _tool(
            name="list_applications",
            description="List applications with cursor pagination and filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["Hired", "Archived", "Active", "Lead"]},
                    "jobId": {"type": "string", "description": "Filter by job"},
                    "createdAfter": {"type": "integer", "description": "Unix epoch millis"},
                    "expand": {"type": "array", "items": {"type": "string", "enum": ["openings"]}},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        _tool(
            name="get_application",
            description=(
                "Fetch a single application by id. Use `expand` to include openings / "
                "form submissions / referrals (`referrals` is only accepted when fetching "
                "by applicationId, not by submittedFormInstanceId)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "submittedFormInstanceId": {
                        "type": "string",
                        "description": "Alternative to applicationId — fetch by form submission id",
                    },
                    "expand": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["openings", "applicationFormSubmissions", "referrals"],
                        },
                    },
                },
            },
        ),
        _tool(
            name="update_application",
            description="Update an application's metadata (source, createdAt, credited user, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "sourceId": {"type": "string"},
                    "creditedToUserId": {"type": "string"},
                    "createdAt": {"type": "string", "description": "ISO date"},
                    "sendNotifications": {
                        "type": "boolean",
                        "description": "Notify subscribed users (default true)",
                    },
                },
                "required": ["applicationId"],
            },
        ),
        _tool(
            name="change_application_stage",
            description="Move an application to a different interview stage. When moving to an Archived stage, archiveReasonId is required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "interviewStageId": {"type": "string"},
                    "archiveReasonId": {
                        "type": "string",
                        "description": "Required when target stage type is 'Archived'",
                    },
                },
                "required": ["applicationId", "interviewStageId"],
            },
        ),
        _tool(
            name="change_application_source",
            description="Change an application's source attribution. Pass sourceId=null to clear the source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "sourceId": {"type": ["string", "null"]},
                },
                "required": ["applicationId", "sourceId"],
            },
        ),
        _tool(
            name="transfer_application",
            description=(
                "Transfer an application to a different job. Ashby requires the target "
                "job's interview plan and the stage to land in — discover them with "
                "list_interview_plans and list_interview_stages first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "jobId": {
                        "type": "string",
                        "description": "Job to transfer the application to",
                    },
                    "interviewPlanId": {
                        "type": "string",
                        "description": "Interview plan on the target job (required by Ashby)",
                    },
                    "interviewStageId": {
                        "type": "string",
                        "description": "Stage within that plan to place the application in (required by Ashby)",
                    },
                    "startAutomaticActivities": {"type": "boolean", "description": "Default true"},
                },
                "required": ["applicationId", "jobId", "interviewPlanId", "interviewStageId"],
            },
        ),
        _tool(
            name="add_application_hiring_team_member",
            description="Assign a user to a hiring team role on an application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "teamMemberId": {"type": "string", "description": "User id to assign"},
                    "roleId": {"type": "string", "description": "Hiring team role id"},
                },
                "required": ["applicationId", "teamMemberId", "roleId"],
            },
        ),
        _tool(
            name="remove_application_hiring_team_member",
            description="Remove a user from a hiring team role on an application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "teamMemberId": {"type": "string"},
                    "roleId": {"type": "string"},
                },
                "required": ["applicationId", "teamMemberId", "roleId"],
            },
        ),
        # Interview Management Tools
        #
        # Ashby splits this into two endpoint groups:
        #   /interview.*          — read interview-type definitions (the templates configured per job)
        #   /interviewSchedule.*  — create/list/update/cancel actual scheduled interview events
        _tool(
            name="get_interview",
            description="Fetch a single interview-type definition by id (not a scheduled event; see get_interview_schedule for that).",
            inputSchema={
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Interview id"}},
                "required": ["id"],
            },
        ),
        _tool(
            name="list_interviews",
            description="List interview-type definitions configured in the workspace.",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {"type": "boolean"},
                    "includeNonSharedInterviews": {
                        "type": "boolean",
                        "description": "Default false; set true to include interviews tied to specific jobs",
                    },
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        _tool(
            name="create_interview_schedule",
            description=(
                "Create a scheduled set of interview events for an application. "
                "Each event specifies startTime (ISO 8601), endTime (ISO 8601), and a list of interviewers (by email)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "interviewEvents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "startTime": {
                                    "type": "string",
                                    "description": "ISO 8601, e.g. 2023-01-30T15:00:00.000Z",
                                },
                                "endTime": {"type": "string", "description": "ISO 8601"},
                                "interviewers": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "email": {"type": "string"},
                                            "feedbackRequired": {"type": "boolean"},
                                        },
                                        "required": ["email"],
                                    },
                                },
                                "interviewId": {
                                    "type": "string",
                                    "description": "Id of the interview-type this event uses",
                                },
                            },
                            "required": ["startTime", "endTime", "interviewers"],
                        },
                    },
                },
                "required": ["applicationId", "interviewEvents"],
            },
        ),
        _tool(
            name="list_interview_schedules",
            description="List scheduled interview events, optionally filtered by application or stage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "interviewStageId": {"type": "string"},
                    "createdAfter": {"type": "integer", "description": "Unix epoch millis"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        _tool(
            name="update_interview_schedule",
            description="Create or update a single event on an existing interview schedule. Only schedules created by the same API key can be updated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "interviewScheduleId": {"type": "string"},
                    "interviewEvent": {
                        "type": "object",
                        "description": "Pass interviewEventId to update an existing event; omit to create a new one",
                        "properties": {
                            "interviewEventId": {"type": "string"},
                            "startTime": {"type": "string"},
                            "endTime": {"type": "string"},
                            "interviewers": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "email": {"type": "string"},
                                        "feedbackRequired": {"type": "boolean"},
                                    },
                                    "required": ["email"],
                                },
                            },
                            "interviewId": {"type": "string"},
                        },
                    },
                },
                "required": ["interviewScheduleId", "interviewEvent"],
            },
        ),
        _tool(
            name="cancel_interview_schedule",
            description="Cancel a scheduled interview. Set allowReschedule=true if the candidate may reschedule.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Interview schedule id"},
                    "allowReschedule": {"type": "boolean", "description": "Default false"},
                },
                "required": ["id"],
            },
        ),
        _tool(
            name="list_interview_events",
            description=(
                "List the individual interview events for a given schedule. "
                "Typical flow: list_interview_schedules (filtered by applicationId) → "
                "pass each schedule's id into this to get the actual events with start/end times and interviewers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "interviewScheduleId": {"type": "string"},
                    "expand": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["interview"]},
                        "description": "Optional — include the interview-type definition for each event",
                    },
                },
                "required": ["interviewScheduleId"],
            },
        ),
        _tool(
            name="list_interview_plans",
            description="List all interview plans in the workspace. Useful for discovering interviewPlanId values for create_application / transfer_application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {
                        "type": "boolean",
                        "description": "Include archived plans (default false)",
                    }
                },
            },
        ),
        _tool(
            name="list_interview_stages",
            description="List all interview stages for a given interview plan, in order. Use this to discover interviewStageId values for change_application_stage / transfer_application.",
            inputSchema={
                "type": "object",
                "properties": {"interviewPlanId": {"type": "string"}},
                "required": ["interviewPlanId"],
            },
        ),
        _tool(
            name="get_interview_stage",
            description="Fetch a single interview stage by id.",
            inputSchema={
                "type": "object",
                "properties": {"interviewStageId": {"type": "string"}},
                "required": ["interviewStageId"],
            },
        ),
        _tool(
            name="list_interview_stage_groups",
            description="List interview stage groups for an interview plan, in order. Groups organize stages into logical phases (e.g. Pre-Screen, Onsite, Offer).",
            inputSchema={
                "type": "object",
                "properties": {"interviewPlanId": {"type": "string"}},
                "required": ["interviewPlanId"],
            },
        ),
        _tool(
            name="list_sources",
            description="List all candidate sources defined in the workspace. Returns id and title for each source — use the id with create_candidate (sourceId) and change_application_source. Requires hiringProcessMetadataRead permission.",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {
                        "type": "boolean",
                        "description": "Include archived sources in results (default false)",
                    }
                },
            },
        ),
        _tool(
            name="list_application_feedback",
            description=(
                "List interview feedback submissions for an application. "
                "Each submission is a filled-out feedback form from one interviewer "
                "after one interview event. Returns scores and free-text answers. "
                "Use this to synthesize themes across an onsite, compare interviewer "
                "reads, or audit hiring decisions. Typical flow: list_applications "
                "or list_interview_schedules to find applicationIds, then this tool "
                "per candidate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["applicationId"],
            },
        ),
    ]


# Built once at import so an unclassified tool fails loudly, here.
_CATALOG: list[types.Tool] = _catalog()
ALL_TOOL_NAMES = frozenset(t.name for t in _CATALOG)
READ_ONLY_TOOLS = frozenset(name for name in ALL_TOOL_NAMES if _HINTS[name].read_only)
WRITE_TOOLS = ALL_TOOL_NAMES - READ_ONLY_TOOLS


def tool_blocked_reason(name: str) -> str | None:
    """Why `name` is unavailable under the current policy, or None if it may run.

    Used by all_tools() to hide the tool and by handlers.dispatch() to
    reject it, so a client that ignores tools/list gets the same answer.
    """
    if name in WRITE_TOOLS and policy.read_only_mode():
        return "this server is running in read-only mode (ASHBY_READ_ONLY is set)"
    if name in LOCAL_FILE_TOOLS and not policy.uploads_enabled():
        return (
            "file uploads are disabled over the HTTP transport; set ASHBY_UPLOAD_DIR "
            "on the server to the directory it may upload files from to enable them"
        )
    return None


def all_tools() -> list[types.Tool]:
    """The tools exposed to the connected client under the current policy."""
    return [t for t in _CATALOG if tool_blocked_reason(t.name) is None]
