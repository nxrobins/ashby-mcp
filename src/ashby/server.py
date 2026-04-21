# /// script
# dependencies = [
#   "mcp",
#   "requests",
#   "python-dotenv"
# ]
# ///
import asyncio
import json
from typing import Any, Optional
import os
from dotenv import load_dotenv
import requests

import mcp.types as types
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio

class AshbyClient:
    """Handles Ashby operations and caching."""
    
    def __init__(self):
        self.api_key: Optional[str] = None
        self.base_url = "https://api.ashbyhq.com"
        self.headers = {}

    def connect(self) -> bool:
        """Establishes connection to Ashby using API key from environment variables.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.api_key = os.getenv('ASHBY_API_KEY')
            if not self.api_key:
                raise ValueError("ASHBY_API_KEY environment variable not set")
            
            self.headers = {
                "Content-Type": "application/json"
            }
            return True
        except Exception as e:
            print(f"Ashby connection failed: {str(e)}")
            return False

    def _make_request(self, endpoint: str, method: str = "GET", data: Optional[dict] = None) -> dict:
        """Make a request to the Ashby API.
        
        Args:
            endpoint (str): The API endpoint to call
            method (str): HTTP method (GET, POST, etc.)
            data (Optional[dict]): Data to send with the request
            
        Returns:
            dict: Response from the API
        """
        if not self.api_key:
            raise ValueError("Ashby connection not established")
            
        url = f"{self.base_url}{endpoint}"
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
            auth=(self.api_key, "")
        )
        response.raise_for_status()
        return response.json()

    def _make_multipart_request(
        self,
        endpoint: str,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
    ) -> dict:
        """Make a multipart/form-data request to the Ashby API (for file uploads).

        Does NOT send the JSON Content-Type header — `requests` sets the
        multipart boundary automatically when `files` is provided.
        """
        if not self.api_key:
            raise ValueError("Ashby connection not established")

        url = f"{self.base_url}{endpoint}"
        response = requests.post(
            url,
            data=data,
            files=files,
            auth=(self.api_key, ""),
        )
        response.raise_for_status()
        return response.json()

# Create a server instance
server = Server("ashby-mcp")

# Load environment variables
load_dotenv()

# Configure with Ashby API key from environment variables
ashby_client = AshbyClient()
if not ashby_client.connect():
    print("Failed to initialize Ashby connection")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools for Ashby operations.
    """
    return [
        # Candidate Management Tools
        types.Tool(
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
                        "description": "Additional email addresses"
                    },
                    "sourceId": {"type": "string", "description": "ID of the source to attribute the candidate to"},
                    "creditedToUserId": {"type": "string", "description": "ID of the user the candidate is credited to"},
                    "location": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "region": {"type": "string"},
                            "country": {"type": "string"}
                        },
                        "description": "Candidate's location"
                    },
                    "createdAt": {"type": "string", "description": "ISO 8601 override for createdAt"}
                },
                "required": ["name"]
            }
        ),
        types.Tool(
            name="search_candidates",
            description="Search for candidates by email and/or name",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Candidate's email"},
                    "name": {"type": "string", "description": "Candidate's name"}
                }
            }
        ),
        types.Tool(
            name="list_candidates",
            description="List candidates. Uses Ashby's cursor-based pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cursor": {"type": "string", "description": "Opaque pagination cursor returned by a prior call"},
                    "syncToken": {"type": "string", "description": "Token from a previous full sync — returns only changes since"},
                    "limit": {"type": "integer", "description": "Max results per page (1-100, default 100)"}
                }
            }
        ),
        types.Tool(
            name="get_candidate",
            description="Fetch a single candidate by ID (full record including custom fields, applications, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Candidate ID"}
                },
                "required": ["id"]
            }
        ),
        types.Tool(
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
                    "alternateEmail": {"type": "string", "description": "Alternate email address to add to the candidate's profile"},
                    "sourceId": {"type": "string"},
                    "creditedToUserId": {"type": "string"},
                    "location": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "region": {"type": "string"},
                            "country": {"type": "string"}
                        }
                    },
                    "socialLinks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "url": {"type": "string"}
                            }
                        },
                        "description": "Replaces existing socialLinks. If sent, linkedInUrl/githubUrl/websiteUrl are ignored."
                    },
                    "createdAt": {"type": "string", "description": "ISO 8601 date override"}
                },
                "required": ["candidateId"]
            }
        ),
        types.Tool(
            name="add_candidate_tag",
            description="Attach a tag to a candidate. Use list_candidate_tags to discover tagId.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "tagId": {"type": "string"}
                },
                "required": ["candidateId", "tagId"]
            }
        ),
        types.Tool(
            name="list_candidate_tags",
            description="List all candidate tags available in the Ashby workspace (for discovering tagId).",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {"type": "boolean", "description": "Include archived tags (default false)"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"}
                }
            }
        ),
        types.Tool(
            name="add_candidate_to_project",
            description="Attach a candidate to a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "projectId": {"type": "string"}
                },
                "required": ["candidateId", "projectId"]
            }
        ),
        types.Tool(
            name="create_candidate_note",
            description="Add a note to a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "note": {"type": "string", "description": "Note text"},
                    "createdAt": {"type": "string", "description": "ISO 8601 timestamp override"}
                },
                "required": ["candidateId", "note"]
            }
        ),
        types.Tool(
            name="list_candidate_notes",
            description="List notes attached to a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["candidateId"]
            }
        ),
        types.Tool(
            name="list_candidate_client_info",
            description="List client info records (e.g. agency submissions) for a candidate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["candidateId"]
            }
        ),
        types.Tool(
            name="anonymize_candidate",
            description="Anonymize a candidate (GDPR / data retention). Irreversible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"}
                },
                "required": ["candidateId"]
            }
        ),
        types.Tool(
            name="upload_candidate_resume",
            description="Upload a resume to a candidate. `file_path` must be a path on the machine running this MCP server.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "file_path": {"type": "string", "description": "Absolute local path to the resume file (PDF, docx, etc.)"}
                },
                "required": ["candidateId", "file_path"]
            }
        ),
        types.Tool(
            name="upload_candidate_file",
            description="Upload an arbitrary file to a candidate. `file_path` must be a path on the machine running this MCP server.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "file_path": {"type": "string", "description": "Absolute local path to the file"}
                },
                "required": ["candidateId", "file_path"]
            }
        ),

        # Project Tools
        types.Tool(
            name="get_project",
            description="Fetch a single project by id (returns title, archived state, associated jobs, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "projectId": {"type": "string"}
                },
                "required": ["projectId"]
            }
        ),
        types.Tool(
            name="list_projects",
            description="List all projects with cursor-based pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cursor": {"type": "string", "description": "Opaque pagination cursor"},
                    "syncToken": {"type": "string", "description": "Token from a previous full sync — returns only changes since"},
                    "limit": {"type": "integer", "description": "Max results (1-100, default 100)"}
                }
            }
        ),
        types.Tool(
            name="search_projects",
            description="Search projects by title (required). Capped at 100 results — use list_projects with pagination to scan everything.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Project title to search for"}
                },
                "required": ["title"]
            }
        ),

        # Custom Field Tools
        types.Tool(
            name="list_custom_fields",
            description="List all custom fields defined in the workspace. Use the optional `objectType` arg to filter client-side (e.g. only Candidate fields for referral data). Returns field id, title, fieldType, and selectableValues you'll need for set_custom_field_value.",
            inputSchema={
                "type": "object",
                "properties": {
                    "objectType": {
                        "type": "string",
                        "enum": ["Application", "Candidate", "Job", "Employee", "Talent_Project", "Opening_Version", "Offer_Version"],
                        "description": "Client-side filter — only return fields attached to this object type"
                    },
                    "includeArchived": {"type": "boolean", "description": "Include archived fields (default false)"},
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"}
                }
            }
        ),
        types.Tool(
            name="get_custom_field",
            description="Fetch a single custom field definition by id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customFieldId": {"type": "string"}
                },
                "required": ["customFieldId"]
            }
        ),
        types.Tool(
            name="create_custom_field",
            description="Create a new custom field definition. Rare/admin operation — requires hiringProcessMetadataWrite permission.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "fieldType": {
                        "type": "string",
                        "enum": ["Boolean", "CompensationRange", "Date", "LongText", "MultiValueSelect", "Number", "NumberRange", "String", "ValueSelect"]
                    },
                    "objectType": {
                        "type": "string",
                        "enum": ["Application", "Candidate", "Job", "Employee", "Talent_Project", "Opening_Version", "Offer_Version"]
                    },
                    "description": {"type": "string"},
                    "selectableValues": {
                        "type": "array",
                        "description": "Required for ValueSelect/MultiValueSelect. Array of { label, value } objects.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"}
                            },
                            "required": ["label", "value"]
                        }
                    },
                    "isDateOnlyField": {"type": "boolean", "description": "Date fields only — whether the field has no time component"},
                    "isExposableToCandidate": {"type": "boolean", "description": "Must be true for the field to be usable in email templates (default false)"}
                },
                "required": ["title", "fieldType", "objectType"]
            }
        ),
        types.Tool(
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
                "  NumberRange → { \"type\": \"number-range\", \"minValue\": N, \"maxValue\": N }\n"
                "Use list_custom_fields first to discover fieldId and the allowed value set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "objectId": {"type": "string", "description": "ID of the Candidate / Application / Job / Opening"},
                    "objectType": {
                        "type": "string",
                        "enum": ["Application", "Candidate", "Job", "Opening"]
                    },
                    "fieldId": {"type": "string", "description": "Custom field definition id (from list_custom_fields)"},
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
                                    "maxValue": {"type": "number"}
                                }
                            }
                        ]
                    }
                },
                "required": ["objectId", "objectType", "fieldId", "fieldValue"]
            }
        ),

        # Job Management Tools
        types.Tool(
            name="create_job",
            description="Create a new job. Requires `title`. Ashby uses IDs for team, location, and interview plan — discover them via list_departments / list_locations / list_interview_plans (not yet exposed) or via the Ashby UI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Job title"},
                    "teamId": {"type": "string", "description": "Department/team id"},
                    "locationId": {"type": "string", "description": "Primary location id"},
                    "defaultInterviewPlanId": {"type": "string", "description": "Required for the job to be opened"},
                    "jobTemplateId": {"type": "string", "description": "Id of an active job template"},
                    "brandId": {"type": "string"}
                },
                "required": ["title"]
            }
        ),
        types.Tool(
            name="search_jobs",
            description="Search jobs by title (required). Use list_jobs to enumerate without a title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Job title to search for"},
                    "location": {"type": "string", "description": "Filter by location"},
                    "department": {"type": "string", "description": "Filter by department"},
                    "include_unlisted": {"type": "boolean", "description": "Include unlisted jobs"}
                },
                "required": ["title"]
            }
        ),
        types.Tool(
            name="list_jobs",
            description="List all jobs, optionally filtered by status (Open, Closed, Archived, Draft). Defaults to Open jobs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["Draft", "Open", "Closed", "Archived"]},
                        "description": "Statuses to include. Defaults to [\"Open\"].",
                    },
                    "openedAfter": {"type": "integer", "description": "Return jobs opened after this unix epoch millis timestamp"},
                    "openedBefore": {"type": "integer", "description": "Return jobs opened before this unix epoch millis timestamp"},
                    "cursor": {"type": "string", "description": "Pagination cursor from a previous response"},
                    "limit": {"type": "integer", "description": "Max results per page"}
                }
            }
        ),
        types.Tool(
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
                        "description": "Optional related objects to expand"
                    }
                },
                "required": ["id"]
            }
        ),
        types.Tool(
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
                    "customRequisitionId": {"type": "string"}
                },
                "required": ["jobId"]
            }
        ),
        types.Tool(
            name="set_job_status",
            description="Change a job's status (Draft, Open, Closed, Archived).",
            inputSchema={
                "type": "object",
                "properties": {
                    "jobId": {"type": "string"},
                    "status": {"type": "string", "enum": ["Draft", "Open", "Closed", "Archived"]}
                },
                "required": ["jobId", "status"]
            }
        ),

        # Application Management Tools
        types.Tool(
            name="create_application",
            description="Create a new application — consider a candidate for a job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidateId": {"type": "string"},
                    "jobId": {"type": "string"},
                    "interviewPlanId": {"type": "string", "description": "Defaults to the job's default plan"},
                    "interviewStageId": {"type": "string", "description": "Stage within the plan; 'FirstPreInterviewScreen' is a special accepted value"},
                    "sourceId": {"type": "string", "description": "Source attribution"},
                    "creditedToUserId": {"type": "string"},
                    "createdAt": {"type": "string", "description": "ISO date override"}
                },
                "required": ["candidateId", "jobId"]
            }
        ),
        types.Tool(
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
                    "limit": {"type": "integer"}
                }
            }
        ),
        types.Tool(
            name="get_application",
            description="Fetch a single application by id. Use `expand` to include openings / form submissions / referrals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "submittedFormInstanceId": {"type": "string", "description": "Alternative to applicationId — fetch by form submission id"},
                    "expand": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["openings", "applicationFormSubmissions", "referrals"]}
                    }
                }
            }
        ),
        types.Tool(
            name="update_application",
            description="Update an application's metadata (source, createdAt, credited user, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "sourceId": {"type": "string"},
                    "creditedToUserId": {"type": "string"},
                    "createdAt": {"type": "string", "description": "ISO date"},
                    "sendNotifications": {"type": "boolean", "description": "Notify subscribed users (default true)"}
                },
                "required": ["applicationId"]
            }
        ),
        types.Tool(
            name="change_application_stage",
            description="Move an application to a different interview stage. When moving to an Archived stage, archiveReasonId is required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "interviewStageId": {"type": "string"},
                    "archiveReasonId": {"type": "string", "description": "Required when target stage type is 'Archived'"}
                },
                "required": ["applicationId", "interviewStageId"]
            }
        ),
        types.Tool(
            name="change_application_source",
            description="Change an application's source attribution. Pass sourceId=null to clear the source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "sourceId": {"type": ["string", "null"]}
                },
                "required": ["applicationId", "sourceId"]
            }
        ),
        types.Tool(
            name="transfer_application",
            description="Transfer an application to a different job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "jobId": {"type": "string"},
                    "interviewPlanId": {"type": "string"},
                    "interviewStageId": {"type": "string"},
                    "startAutomaticActivities": {"type": "boolean", "description": "Default true"}
                },
                "required": ["applicationId", "jobId"]
            }
        ),
        types.Tool(
            name="add_application_hiring_team_member",
            description="Assign a user to a hiring team role on an application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "teamMemberId": {"type": "string", "description": "User id to assign"},
                    "roleId": {"type": "string", "description": "Hiring team role id"}
                },
                "required": ["applicationId", "teamMemberId", "roleId"]
            }
        ),
        types.Tool(
            name="remove_application_hiring_team_member",
            description="Remove a user from a hiring team role on an application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "applicationId": {"type": "string"},
                    "teamMemberId": {"type": "string"},
                    "roleId": {"type": "string"}
                },
                "required": ["applicationId", "teamMemberId", "roleId"]
            }
        ),
        
        # Interview Management Tools
        #
        # Ashby splits this into two endpoint groups:
        #   /interview.*          — read interview-type definitions (the templates configured per job)
        #   /interviewSchedule.*  — create/list/update/cancel actual scheduled interview events
        types.Tool(
            name="get_interview",
            description="Fetch a single interview-type definition by id (not a scheduled event; see get_interview_schedule for that).",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Interview id"}
                },
                "required": ["id"]
            }
        ),
        types.Tool(
            name="list_interviews",
            description="List interview-type definitions configured in the workspace.",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {"type": "boolean"},
                    "includeNonSharedInterviews": {
                        "type": "boolean",
                        "description": "Default false; set true to include interviews tied to specific jobs"
                    },
                    "cursor": {"type": "string"},
                    "syncToken": {"type": "string"},
                    "limit": {"type": "integer"}
                }
            }
        ),
        types.Tool(
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
                                "startTime": {"type": "string", "description": "ISO 8601, e.g. 2023-01-30T15:00:00.000Z"},
                                "endTime": {"type": "string", "description": "ISO 8601"},
                                "interviewers": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "email": {"type": "string"},
                                            "feedbackRequired": {"type": "boolean"}
                                        },
                                        "required": ["email"]
                                    }
                                },
                                "interviewId": {"type": "string", "description": "Id of the interview-type this event uses"}
                            },
                            "required": ["startTime", "endTime", "interviewers"]
                        }
                    }
                },
                "required": ["applicationId", "interviewEvents"]
            }
        ),
        types.Tool(
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
                    "limit": {"type": "integer"}
                }
            }
        ),
        types.Tool(
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
                                        "feedbackRequired": {"type": "boolean"}
                                    },
                                    "required": ["email"]
                                }
                            },
                            "interviewId": {"type": "string"}
                        }
                    }
                },
                "required": ["interviewScheduleId", "interviewEvent"]
            }
        ),
        types.Tool(
            name="cancel_interview_schedule",
            description="Cancel a scheduled interview. Set allowReschedule=true if the candidate may reschedule.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Interview schedule id"},
                    "allowReschedule": {"type": "boolean", "description": "Default false"}
                },
                "required": ["id"]
            }
        ),
        types.Tool(
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
                        "description": "Optional — include the interview-type definition for each event"
                    }
                },
                "required": ["interviewScheduleId"]
            }
        ),
        types.Tool(
            name="list_interview_plans",
            description="List all interview plans in the workspace. Useful for discovering interviewPlanId values for create_application / transfer_application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "includeArchived": {"type": "boolean", "description": "Include archived plans (default false)"}
                }
            }
        ),
        types.Tool(
            name="list_interview_stages",
            description="List all interview stages for a given interview plan, in order. Use this to discover interviewStageId values for change_application_stage / transfer_application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "interviewPlanId": {"type": "string"}
                },
                "required": ["interviewPlanId"]
            }
        ),
        types.Tool(
            name="get_interview_stage",
            description="Fetch a single interview stage by id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "interviewStageId": {"type": "string"}
                },
                "required": ["interviewStageId"]
            }
        ),
        types.Tool(
            name="list_interview_stage_groups",
            description="List interview stage groups for an interview plan, in order. Groups organize stages into logical phases (e.g. Pre-Screen, Onsite, Offer).",
            inputSchema={
                "type": "object",
                "properties": {
                    "interviewPlanId": {"type": "string"}
                },
                "required": ["interviewPlanId"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls by routing to appropriate Ashby API endpoints."""
    try:
        if name == "create_candidate":
            response = ashby_client._make_request(
                "/candidate.create",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Created candidate: {json.dumps(response, indent=2)}")]
            
        elif name == "search_candidates":
            response = ashby_client._make_request(
                "/candidate.search",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Search results: {json.dumps(response, indent=2)}")]
            
        elif name == "list_candidates":
            response = ashby_client._make_request(
                "/candidate.list",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Candidate list: {json.dumps(response, indent=2)}")]

        elif name == "get_candidate":
            response = ashby_client._make_request(
                "/candidate.info",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Candidate: {json.dumps(response, indent=2)}")]

        elif name == "update_candidate":
            response = ashby_client._make_request(
                "/candidate.update",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Updated candidate: {json.dumps(response, indent=2)}")]

        elif name == "add_candidate_tag":
            response = ashby_client._make_request(
                "/candidate.addTag",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Tag added: {json.dumps(response, indent=2)}")]

        elif name == "list_candidate_tags":
            response = ashby_client._make_request(
                "/candidateTag.list",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Candidate tags: {json.dumps(response, indent=2)}")]

        elif name == "add_candidate_to_project":
            response = ashby_client._make_request(
                "/candidate.addProject",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Project added: {json.dumps(response, indent=2)}")]

        elif name == "create_candidate_note":
            response = ashby_client._make_request(
                "/candidate.createNote",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Note created: {json.dumps(response, indent=2)}")]

        elif name == "list_candidate_notes":
            response = ashby_client._make_request(
                "/candidate.listNotes",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Candidate notes: {json.dumps(response, indent=2)}")]

        elif name == "list_candidate_client_info":
            response = ashby_client._make_request(
                "/candidate.listClientInfo",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Candidate client info: {json.dumps(response, indent=2)}")]

        elif name == "anonymize_candidate":
            response = ashby_client._make_request(
                "/candidate.anonymize",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Anonymized: {json.dumps(response, indent=2)}")]

        elif name == "upload_candidate_resume":
            path = arguments["file_path"]
            with open(path, "rb") as f:
                response = ashby_client._make_multipart_request(
                    "/candidate.uploadResume",
                    data={"candidateId": arguments["candidateId"]},
                    files={"resume": (os.path.basename(path), f)},
                )
            return [types.TextContent(type="text", text=f"Resume uploaded: {json.dumps(response, indent=2)}")]

        elif name == "upload_candidate_file":
            path = arguments["file_path"]
            with open(path, "rb") as f:
                response = ashby_client._make_multipart_request(
                    "/candidate.uploadFile",
                    data={"candidateId": arguments["candidateId"]},
                    files={"file": (os.path.basename(path), f)},
                )
            return [types.TextContent(type="text", text=f"File uploaded: {json.dumps(response, indent=2)}")]

        elif name == "get_project":
            response = ashby_client._make_request(
                "/project.info",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Project: {json.dumps(response, indent=2)}")]

        elif name == "list_projects":
            response = ashby_client._make_request(
                "/project.list",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Projects: {json.dumps(response, indent=2)}")]

        elif name == "search_projects":
            response = ashby_client._make_request(
                "/project.search",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Project search results: {json.dumps(response, indent=2)}")]

        elif name == "list_custom_fields":
            # Client-side objectType filter, since /customField.list doesn't support it server-side.
            payload = {k: v for k, v in (arguments or {}).items() if k != "objectType"}
            response = ashby_client._make_request(
                "/customField.list",
                method="POST",
                data=payload
            )
            object_type_filter = (arguments or {}).get("objectType")
            if object_type_filter and isinstance(response, dict) and isinstance(response.get("results"), list):
                filtered = [f for f in response["results"] if f.get("objectType") == object_type_filter]
                response = {**response, "results": filtered, "filteredBy": {"objectType": object_type_filter}}
            return [types.TextContent(type="text", text=f"Custom fields: {json.dumps(response, indent=2)}")]

        elif name == "get_custom_field":
            response = ashby_client._make_request(
                "/customField.info",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Custom field: {json.dumps(response, indent=2)}")]

        elif name == "create_custom_field":
            response = ashby_client._make_request(
                "/customField.create",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Custom field created: {json.dumps(response, indent=2)}")]

        elif name == "set_custom_field_value":
            response = ashby_client._make_request(
                "/customField.setValue",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Custom field value set: {json.dumps(response, indent=2)}")]

        elif name == "create_job":
            response = ashby_client._make_request(
                "/job.create",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Created job: {json.dumps(response, indent=2)}")]
            
        elif name == "search_jobs":
            response = ashby_client._make_request(
                "/job.search",
                method="POST",
                data=arguments
            )
            return [types.TextContent(type="text", text=f"Job search results: {json.dumps(response, indent=2)}")]

        elif name == "list_jobs":
            payload = dict(arguments) if arguments else {}
            payload.setdefault("status", ["Open"])
            response = ashby_client._make_request(
                "/job.list",
                method="POST",
                data=payload
            )
            return [types.TextContent(type="text", text=f"Job list: {json.dumps(response, indent=2)}")]

        elif name == "get_job":
            response = ashby_client._make_request("/job.info", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Job: {json.dumps(response, indent=2)}")]

        elif name == "update_job":
            response = ashby_client._make_request("/job.update", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Job updated: {json.dumps(response, indent=2)}")]

        elif name == "set_job_status":
            response = ashby_client._make_request("/job.setStatus", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Job status set: {json.dumps(response, indent=2)}")]

        elif name == "create_application":
            response = ashby_client._make_request("/application.create", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Created application: {json.dumps(response, indent=2)}")]

        elif name == "list_applications":
            response = ashby_client._make_request("/application.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Applications: {json.dumps(response, indent=2)}")]

        elif name == "get_application":
            response = ashby_client._make_request("/application.info", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Application: {json.dumps(response, indent=2)}")]

        elif name == "update_application":
            response = ashby_client._make_request("/application.update", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Application updated: {json.dumps(response, indent=2)}")]

        elif name == "change_application_stage":
            response = ashby_client._make_request("/application.change_stage", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Stage changed: {json.dumps(response, indent=2)}")]

        elif name == "change_application_source":
            response = ashby_client._make_request("/application.change_source", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Source changed: {json.dumps(response, indent=2)}")]

        elif name == "transfer_application":
            response = ashby_client._make_request("/application.transfer", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Application transferred: {json.dumps(response, indent=2)}")]

        elif name == "add_application_hiring_team_member":
            response = ashby_client._make_request("/application.addHiringTeamMember", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Hiring team member added: {json.dumps(response, indent=2)}")]

        elif name == "remove_application_hiring_team_member":
            response = ashby_client._make_request("/application.removeHiringTeamMember", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Hiring team member removed: {json.dumps(response, indent=2)}")]

        elif name == "get_interview":
            response = ashby_client._make_request("/interview.info", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview: {json.dumps(response, indent=2)}")]

        elif name == "list_interviews":
            response = ashby_client._make_request("/interview.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interviews: {json.dumps(response, indent=2)}")]

        elif name == "create_interview_schedule":
            response = ashby_client._make_request("/interviewSchedule.create", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview scheduled: {json.dumps(response, indent=2)}")]

        elif name == "list_interview_schedules":
            response = ashby_client._make_request("/interviewSchedule.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview schedules: {json.dumps(response, indent=2)}")]

        elif name == "update_interview_schedule":
            response = ashby_client._make_request("/interviewSchedule.update", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview schedule updated: {json.dumps(response, indent=2)}")]

        elif name == "cancel_interview_schedule":
            response = ashby_client._make_request("/interviewSchedule.cancel", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview schedule cancelled: {json.dumps(response, indent=2)}")]

        elif name == "list_interview_events":
            response = ashby_client._make_request("/interviewEvent.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview events: {json.dumps(response, indent=2)}")]

        elif name == "list_interview_plans":
            response = ashby_client._make_request("/interviewPlan.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview plans: {json.dumps(response, indent=2)}")]

        elif name == "list_interview_stages":
            response = ashby_client._make_request("/interviewStage.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview stages: {json.dumps(response, indent=2)}")]

        elif name == "get_interview_stage":
            response = ashby_client._make_request("/interviewStage.info", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview stage: {json.dumps(response, indent=2)}")]

        elif name == "list_interview_stage_groups":
            response = ashby_client._make_request("/interviewStageGroup.list", method="POST", data=arguments)
            return [types.TextContent(type="text", text=f"Interview stage groups: {json.dumps(response, indent=2)}")]

        else:
            raise ValueError(f"Unknown tool: {name}")
            
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error executing {name}: {str(e)}")]

def _init_options() -> InitializationOptions:
    return InitializationOptions(
        server_name="ashby-mcp",
        server_version="0.1.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def run_stdio() -> None:
    """Run the MCP server over stdio — for Claude Code and other local clients."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, _init_options())


async def run_http(host: str, port: int) -> None:
    """Run the MCP server over HTTP+SSE — for Claude Cowork and other
    remote clients.

    Auth: if `MCP_BEARER_TOKEN` is set, every request must include
    `Authorization: Bearer <token>`. If unset, the server runs open —
    only do that for local testing.
    """
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")
    expected_token = os.getenv("MCP_BEARER_TOKEN")

    def _unauthorized() -> Response:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    def _check_auth(request: Request) -> Response | None:
        if not expected_token:
            return None  # auth disabled
        header = request.headers.get("authorization", "")
        if header != f"Bearer {expected_token}":
            return _unauthorized()
        return None

    async def handle_sse(request: Request) -> Response:
        if (err := _check_auth(request)) is not None:
            return err
        # connect_sse owns the response lifecycle.
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, _init_options())
        return Response()

    async def handle_messages(scope, receive, send) -> None:
        # Manual auth check — Mount gives us raw ASGI, not a Request.
        if expected_token:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization", "") != f"Bearer {expected_token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await sse.handle_post_message(scope, receive, send)

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"ok": True, "auth_required": bool(expected_token)})

    app = Starlette(
        routes=[
            Route("/healthz", endpoint=healthz),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=handle_messages),
        ]
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    await uvicorn.Server(config).serve()


async def run() -> None:
    """Dispatch to stdio (default) or http transport based on MCP_TRANSPORT."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        host = os.getenv("MCP_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_PORT", "8000"))
        await run_http(host, port)
    else:
        await run_stdio()


if __name__ == "__main__":
    asyncio.run(run())