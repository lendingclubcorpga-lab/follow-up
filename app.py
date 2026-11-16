import traceback
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Page layout configurations
st.set_page_config(page_title="Lead Tracking Repository", layout="wide")


# 1. Initialize Supabase connection securely via secrets
@st.cache_resource
def init_supabase() -> Client:
    try:
        url = st.secrets["supabase"]["url"].strip().rstrip("/")
        key = st.secrets["supabase"]["key"].strip()
    except Exception:
        st.error(
            "Missing Supabase secrets. In Streamlit Cloud go to Manage app -> "
            "Settings -> Secrets and add:\n\n"
            "[supabase]\nurl = \"https://<project-ref>.supabase.co\"\nkey = \"<anon-or-service-key>\""
        )
        st.stop()

    # The client wants the bare project URL, not the REST endpoint
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    if not url.startswith("https://"):
        st.error(f"Supabase URL looks wrong: {url!r}. It should look like https://<project-ref>.supabase.co")
        st.stop()

    return create_client(url, key)


supabase = init_supabase()


def show_db_error(action: str, exc: Exception) -> None:
    """Streamlit redacts uncaught errors, so print them ourselves."""
    st.error(f"Could not {action}: {type(exc).__name__}: {exc}")
    if "JSONDecodeError" in type(exc).__name__ or "Expecting value" in str(exc):
        st.warning(
            "Supabase returned a non-JSON response. Most common causes: the project is "
            "paused (restore it in the Supabase dashboard), the URL in secrets is wrong, "
            "or the API key is wrong."
        )
    with st.expander("Technical details"):
        st.code(traceback.format_exc())


st.title("📋 Supabase Lead Repository")

# Role Management Sidebar
# NOTE: this is only a UI switch. Anyone can pick "Hub Owner (Admin)".
# For real protection use authentication plus Row Level Security in Supabase.
st.sidebar.header("🔑 Access Control")
role = st.sidebar.selectbox("Select Your Role", ["Dialer (Staff)", "Hub Owner (Admin)"])

# Preset Status Options
STATUS_OPTIONS = ["Pending", "Success", "Not Interested", "Follow-up Scheduled", "No Answer"]

# -------------------------------------------------------------
# ADMIN WORKFLOW: Add New Leads manually
# -------------------------------------------------------------
if role == "Hub Owner (Admin)":
    st.header("➕ Add New Lead")
    with st.form("add_lead_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            name = st.text_input("Lead Name")
        with col2:
            phone = st.text_input("Phone Number")
        with col3:
            closing_amount = st.number_input("Closing Amount ($)", min_value=0.0, step=100.0)

        status = st.selectbox("Initial Status", STATUS_OPTIONS)
        notes = st.text_area("Additional Text / Message Box Notes")

        submit_btn = st.form_submit_button("Save Lead to Repository")

        if submit_btn:
            if name.strip() and phone.strip():
                try:
                    supabase.table("leads").insert({
                        "name": name.strip(),
                        "phone": phone.strip(),
                        "closing_amount": closing_amount,
                        "status": status,
                        "notes": notes,
                    }).execute()
                except Exception as e:
                    show_db_error("save the lead", e)
                else:
                    st.success(f"Successfully uploaded lead: {name}")
                    st.rerun()
            else:
                st.error("Name and Phone Number are required fields!")

# -------------------------------------------------------------
# REPOSITORY VIEW & UPDATE WORKFLOW (For Admins and Dialers)
# -------------------------------------------------------------
st.header("🔍 Active Pipeline Dashboard")

# Fetch live pipeline rows from Supabase
try:
    response = supabase.table("leads").select("*").order("id", desc=False).execute()
    leads_data = response.data
except Exception as e:
    show_db_error("load leads", e)
    st.stop()

if not leads_data:
    st.info("No leads available in your Supabase repository yet.")
else:
    df = pd.DataFrame(leads_data)

    # Rename columns visually for presentation
    df_display = df.rename(columns={
        "id": "ID", "name": "Name", "phone": "Phone",
        "closing_amount": "Closing Amount ($)", "status": "Status",
        "notes": "Notes", "last_updated": "Last Updated",
    })

    st.dataframe(df_display, width="stretch", hide_index=True)
    st.markdown("---")

    # Selection mapping to match UI picklists to chosen IDs
    st.header("✍️ Update Call Status & Progress")
    lead_options = {f"ID {row['id']} - {row['name']}": row for row in leads_data}
    selected_lead_label = st.selectbox("Select a lead record to modify/update:", list(lead_options.keys()))

    if selected_lead_label:
        selected_lead = lead_options[selected_lead_label]
        lead_id = selected_lead["id"]

        # Build live update fields inside a form. Keys include the lead ID so the
        # fields reset properly when a different lead is selected.
        with st.form("update_lead_form"):
            st.markdown(f"**Modifying Record ID:** {lead_id}")

            col1, col2, col3 = st.columns(3)
            with col1:
                up_name = st.text_input("Edit Name", value=selected_lead.get("name") or "", key=f"name_{lead_id}")
            with col2:
                up_phone = st.text_input("Edit Phone", value=selected_lead.get("phone") or "", key=f"phone_{lead_id}")
            with col3:
                up_amount = st.number_input(
                    "Update Closing Amount ($)",
                    min_value=0.0,
                    value=float(selected_lead.get("closing_amount") or 0),
                    step=50.0,
                    key=f"amount_{lead_id}",
                )

            # Match baseline index safely
            current_status = selected_lead.get("status")
            default_status_idx = STATUS_OPTIONS.index(current_status) if current_status in STATUS_OPTIONS else 0
            up_status = st.selectbox("Update Status", STATUS_OPTIONS, index=default_status_idx, key=f"status_{lead_id}")

            up_notes = st.text_area(
                "Update Message Box / Call History",
                value=selected_lead.get("notes") or "",
                key=f"notes_{lead_id}",
            )

            update_btn = st.form_submit_button("Save Live Updates")

            if update_btn:
                try:
                    supabase.table("leads").update({
                        "name": up_name,
                        "phone": up_phone,
                        "closing_amount": up_amount,
                        "status": up_status,
                        "notes": up_notes,
                        # "now()" would be sent as a literal string, so send a real timestamp
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", lead_id).execute()
                except Exception as e:
                    show_db_error("update the lead", e)
                else:
                    st.success(f"Updates permanently saved for {up_name}!")
                    st.rerun()

# Explanatory safety notices
if role == "Dialer (Staff)":
    st.sidebar.info("🛡️ Staff Security Mode Active: Data deletion structural commands are blocked.")
