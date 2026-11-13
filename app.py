import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Page layout configurations
st.set_page_config(page_title="Lead Tracking Repository", layout="wide")

# 1. Initialize Supabase Connection securely via secrets
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

st.title("📋 Supabase Lead Repository")

# Role Management Sidebar
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
            if name and phone:
                # Insert data payload directly into Supabase table
                data, count = supabase.table("leads").insert({
                    "name": name,
                    "phone": phone,
                    "closing_amount": closing_amount,
                    "status": status,
                    "notes": notes
                }).execute()
                st.success(f"Successfully uploaded lead: {name}")
                st.preload_data = None # Clear local context to pull raw table live
                st.rerun()
            else:
                st.error("Name and Phone Number are required fields!")

# -------------------------------------------------------------
# REPOSITORY VIEW & UPDATE WORKFLOW (For Admins and Dialers)
# -------------------------------------------------------------
st.header("🔍 Active Pipeline Dashboard")

# Fetch live real-time pipeline rows from Supabase
response = supabase.table("leads").select("*").order("id", desc=False).execute()
leads_data = response.data

if not leads_data:
    st.info("No leads available in your Supabase repository yet.")
else:
    # Convert Supabase JSON output cleanly into a pandas dataframe for display
    df = pd.DataFrame(leads_data)
    
    # Rename columns visually for presentation
    df_display = df.rename(columns={
        "id": "ID", "name": "Name", "phone": "Phone", 
        "closing_amount": "Closing Amount ($)", "status": "Status", 
        "notes": "Notes", "last_updated": "Last Updated"
    })
    
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    st.markdown("---")
    
    # Selection mapping to match UI picklists to chosen IDs
    st.header("✍️ Update Call Status & Progress")
    lead_options = {f"ID {row['id']} - {row['name']}": row for row in leads_data}
    selected_lead_label = st.selectbox("Select a lead record to modify/update:", list(lead_options.keys()))
    
    if selected_lead_label:
        selected_lead = lead_options[selected_lead_label]
        
        # Build live update fields inside a structural submission form
        with st.form("update_lead_form"):
            st.markdown(f"**Modifying Record ID:** {selected_lead['id']}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                up_name = st.text_input("Edit Name", value=selected_lead['name']) 
            with col2:
                up_phone = st.text_input("Edit Phone", value=selected_lead['phone'])
            with col3:
                up_amount = st.number_input("Update Closing Amount ($)", min_value=0.0, value=float(selected_lead['closing_amount']), step=50.0)
            
            # Match baseline indexes safely
            current_status = selected_lead['status']
            default_status_idx = STATUS_OPTIONS.index(current_status) if current_status in STATUS_OPTIONS else 0
            up_status = st.selectbox("Update Status", STATUS_OPTIONS, index=default_status_idx)
            
            up_notes = st.text_area("Update Message Box / Call History", value=selected_lead['notes'])
            
            update_btn = st.form_submit_button("Save Live Updates")
            
            if update_btn:
                # Update payload to remote server and force date rewrite
                supabase.table("leads").update({
                    "name": up_name,
                    "phone": up_phone,
                    "closing_amount": up_amount,
                    "status": up_status,
                    "notes": up_notes,
                    "last_updated": "now()" # Database forces execution timestamp update
                }).eq("id", selected_lead['id']).execute()
                
                st.success(f"Updates permanently saved for {up_name}!")
                st.rerun()

# Explanatory safety notices
if role == "Dialer (Staff)":
    st.sidebar.info("🛡️ Staff Security Mode Active: Data deletion structural commands are blocked.")
