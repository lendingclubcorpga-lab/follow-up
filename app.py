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
            "[supabase]\nurl = \"https://<project-ref>.supabase.co\"\nkey = \"<service-role-or-secret-key>\""
        )
        st.stop()

    # The client wants the bare project URL, not the REST endpoint
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]

    if not url.startswith("https://"):
        st.error(f"Supabase URL looks wrong: {url!r}. It should look like https://<project-ref>.supabase.co")
        st.stop()

    host = url.split("//", 1)[1].split("/", 1)[0].lower()
    if host in ("supabase.com", "www.supabase.com", "app.supabase.com") or "/dashboard" in url:
        st.error(
            f"The URL in your secrets points to the Supabase website/dashboard ({url!r}), "
            "not to your project's API. In the Supabase dashboard open your project -> "
            "Project Settings -> API (or Data API) and copy the 'Project URL'. "
            "It looks like https://<project-ref>.supabase.co"
        )
        st.stop()

    return create_client(url, key)


supabase = init_supabase()


def show_db_error(action: str, exc: Exception) -> None:
    """Streamlit redacts uncaught errors, so print them ourselves."""
    st.error(f"Could not {action}: {type(exc).__name__}: {exc}")
    text = str(exc)
    if "JSONDecodeError" in type(exc).__name__ or "Expecting value" in text:
        st.warning(
            "Supabase returned a non-JSON response. Most common causes: the project is "
            "paused (restore it in the Supabase dashboard), the URL in secrets is wrong, "
            "or the API key is wrong."
        )
    if "closer_name" in text:
        st.warning(
            "The 'closer_name' column is missing. Run this in the Supabase SQL Editor:\n\n"
            "alter table public.leads add column if not exists closer_name text default '';"
        )
    with st.expander("Technical details"):
        st.code(traceback.format_exc())


st.title("📋 Supabase Lead Repository")

ADMIN_ROLE = "Hub Owner (Admin)"
STAFF_ROLE = "Dialer (Staff)"

# Role Management Sidebar
st.sidebar.header("🔑 Access Control")
role = st.sidebar.selectbox("Select Your Role", [STAFF_ROLE, ADMIN_ROLE])

# Optional admin password. To turn it on, add this to your Streamlit secrets:
#   [app]
#   admin_password = "choose-something-strong"
# Without it, the role dropdown is only a UI switch and anyone can pick Admin.
if role == ADMIN_ROLE:
    try:
        admin_password = st.secrets["app"]["admin_password"]
    except Exception:
        admin_password = None

    if admin_password:
        entered = st.sidebar.text_input("Admin password", type="password")
        if entered != admin_password:
            if entered:
                st.sidebar.error("Wrong password.")
            st.sidebar.info("Enter the admin password to unlock delete access.")
            role = STAFF_ROLE

is_admin = role == ADMIN_ROLE

# Preset Status Options
STATUS_OPTIONS = ["Pending", "Success", "Not Interested", "Follow-up Scheduled", "No Answer"]

# -------------------------------------------------------------
# ADD NEW LEAD / FOLLOW-UP (Admins and Dialers)
# -------------------------------------------------------------
st.header("➕ Add New Lead / Follow-up")
with st.form("add_lead_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        name = st.text_input("Lead Name")
    with col2:
        phone = st.text_input("Phone Number")
    with col3:
        closer_name = st.text_input("Closer Name")
    with col4:
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
                    "closer_name": closer_name.strip(),
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
# REPOSITORY VIEW & UPDATE WORKFLOW (Admins and Dialers)
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
        "id": "ID", "name": "Name", "phone": "Phone", "closer_name": "Closer Name",
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

        # Keys include the lead ID so the fields reset when a different lead is selected.
        with st.form("update_lead_form"):
            st.markdown(f"**Modifying Record ID:** {lead_id}")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                up_name = st.text_input("Edit Name", value=selected_lead.get("name") or "", key=f"name_{lead_id}")
            with col2:
                up_phone = st.text_input("Edit Phone", value=selected_lead.get("phone") or "", key=f"phone_{lead_id}")
            with col3:
                up_closer = st.text_input(
                    "Edit Closer Name", value=selected_lead.get("closer_name") or "", key=f"closer_{lead_id}"
                )
            with col4:
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
                        "closer_name": up_closer,
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

        # -------------------------------------------------
        # DELETE (Admin only)
        # -------------------------------------------------
        if is_admin:
            st.markdown("---")
            st.header("🗑️ Delete Lead (Admin only)")
            confirm_delete = st.checkbox(
                f"Yes, permanently delete {selected_lead_label}", key=f"confirm_delete_{lead_id}"
            )
            if st.button("Delete Lead", type="primary", disabled=not confirm_delete, key=f"delete_{lead_id}"):
                try:
                    supabase.table("leads").delete().eq("id", lead_id).execute()
                except Exception as e:
                    show_db_error("delete the lead", e)
                else:
                    st.toast(f"Deleted {selected_lead_label}")
                    st.rerun()

# Explanatory safety notices
if not is_admin:
    st.sidebar.info("🛡️ Staff Mode: you can add and update leads, but only the Hub Owner can delete them.")
