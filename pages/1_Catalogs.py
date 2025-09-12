"""Catalog browsing page."""

from __future__ import annotations
import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional, List

import pandas as pd
import streamlit as st

from synthap.config.settings import settings
from synthap.catalogs.loader import load_catalogs, Vendor, Item
from synthap.catalogs.manager import (
    backup_catalogs, 
    restore_catalogs,
    list_backups,
    create_default_backup,
    restore_default_catalogs,
    fix_items_yaml
)
from synthap.ai.schema import SyntheticContactRequest
from synthap.ai.synthgen import (
    preview_synthetic_data,
    apply_synthetic_data
)

def runs_dir() -> Path:
    """Get the runs directory path."""
    p = Path(settings.runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p

def latest_run_id() -> Optional[str]:
    """Get the latest run ID."""
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None

def format_currency(value: float) -> str:
    return f"${value:,.2f}"

def format_vendor_data(vendors: List[Vendor]) -> pd.DataFrame:
    if not vendors:
        # Return an empty DataFrame with the right columns
        return pd.DataFrame(columns=[
            'Vendor Name', 'ID', 'Is Supplier', 'Payment Terms', 
            'Xero Contact ID', 'Xero Account #'
        ])
    
    df = pd.DataFrame([v.model_dump() for v in vendors])
    # Reorder and rename columns for better presentation
    columns = {
        'name': 'Vendor Name',
        'id': 'ID',
        'is_supplier': 'Is Supplier',
        'payment_terms': 'Payment Terms',
        'xero_contact_id': 'Xero Contact ID',
        'xero_account_number': 'Xero Account #'
    }
    
    # Only include columns that exist in the DataFrame
    rename_cols = {k: v for k, v in columns.items() if k in df.columns}
    df = df.rename(columns=rename_cols)
    
    # Select only columns that exist
    available_cols = [col for col in columns.values() if col in df.columns]
    return df[available_cols]


def format_item_data(items: List[Item]) -> pd.DataFrame:
    if not items:
        # Return an empty DataFrame with the right columns
        return pd.DataFrame(columns=[
            'Item Name', 'Item Code', 'Unit Price', 
            'Account Code', 'Tax Code', 'Price Variance'
        ])
    
    df = pd.DataFrame([i.model_dump() for i in items])
    # Format currency and percentages
    if 'unit_price' in df.columns:
        df['unit_price'] = df['unit_price'].apply(format_currency)
    if 'price_variance_pct' in df.columns:
        df['price_variance_pct'] = df['price_variance_pct'].apply(lambda x: f"{x*100:.1f}%")
    
    # Reorder and rename columns
    columns = {
        'name': 'Item Name',
        'code': 'Item Code',
        'unit_price': 'Unit Price',
        'account_code': 'Account Code',
        'tax_code': 'Tax Code',
        'price_variance_pct': 'Price Variance'
    }
    
    # Only include columns that exist in the DataFrame
    rename_cols = {k: v for k, v in columns.items() if k in df.columns}
    df = df.rename(columns=rename_cols)
    
    # Select only columns that exist
    available_cols = [col for col in columns.values() if col in df.columns]
    return df[available_cols]



def format_vendor_items(cat) -> pd.DataFrame:
    # Create a more detailed mapping view
    records = []
    
    if not hasattr(cat, 'vendor_items') or not cat.vendor_items:
        # Return empty DataFrame with proper columns
        return pd.DataFrame(columns=[
            'Vendor Name', 'Vendor ID', 'Item Name', 'Item Code', 'Unit Price'
        ])
    
    for vid, codes in cat.vendor_items.items():
        vendor = next((v for v in cat.vendors if v.id == vid), None)
        if not vendor:
            continue
        
        for code in codes:
            item = next((i for i in cat.items if i.code == code), None)
            if not item:
                continue
                
            records.append({
                'Vendor Name': vendor.name,
                'Vendor ID': vid,
                'Item Name': item.name,
                'Item Code': code,
                'Unit Price': format_currency(item.unit_price)
            })
            
    if not records:
        return pd.DataFrame(columns=[
            'Vendor Name', 'Vendor ID', 'Item Name', 'Item Code', 'Unit Price'
        ])
        
    return pd.DataFrame(records)

def format_payment_terms(payment_terms) -> str:
    """Format payment terms for display."""
    if isinstance(payment_terms, dict):
        term_type = payment_terms.get('type', '')
        days = payment_terms.get('days', '')
        if term_type and days:
            return f"{term_type} - {days} days"
        return str(payment_terms)
    return str(payment_terms)

def render_data_generation_ui():
    st.subheader("Generate Synthetic Data")
    
    # Store preview data in session state
    if "preview_data" not in st.session_state:
        st.session_state.preview_data = None
    
    if "generation_step" not in st.session_state:
        st.session_state.generation_step = "input"  # input, preview, applying, complete
    
    if "generation_results" not in st.session_state:
        st.session_state.generation_results = None
    
    # Input form - shown when no preview exists
    if st.session_state.generation_step == "input":
        with st.form("synthetic_data_form"):
            st.info("Generate synthetic vendors and items for testing based on industry.")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                industry = st.text_input("Industry", value="Construction",
                                        help="Choose an industry to generate relevant contacts and items")
            with col2:
                num_contacts = st.number_input("Number of Contacts", min_value=1, max_value=50, value=5,
                                              help="How many vendor contacts to generate")
            with col3:
                items_per_vendor = st.number_input("Items per Vendor", min_value=1, max_value=20, value=3,
                                                  help="How many items each vendor should provide")
            
            override_existing = st.checkbox("Override Existing Data", value=True,
                                          help="If checked, will replace existing catalog data instead of adding to it")
            
            # Add backup option
            create_backup = st.checkbox("Create Backup Before Generating", value=True,
                                      help="Creates a backup of current catalogs before proceeding")
            
            preview_button = st.form_submit_button("Preview Data")
            
            if preview_button:
                with st.spinner("Generating preview data..."):
                    # Create backup if requested
                    if create_backup:
                        backup_reason = f"before_{industry.lower()}_generation"
                        backup_path = backup_catalogs(reason=backup_reason)
                        st.success(f"Created backup: {Path(backup_path).name}")
                    
                    # Generate preview data
                    request = SyntheticContactRequest(
                        industry=industry,
                        num_contacts=num_contacts,
                        items_per_vendor=items_per_vendor
                    )
                    
                    preview_data = asyncio.run(preview_synthetic_data(request))
                    
                    # Store in session state
                    st.session_state.preview_data = preview_data
                    st.session_state.override_existing = override_existing
                    st.session_state.generation_step = "preview"
                    
                    # Force rerun to show preview
                    st.rerun()
    
    # Preview step - show generated data and confirm
    elif st.session_state.generation_step == "preview":
        preview_data = st.session_state.preview_data
        
        st.success("Preview data generated successfully! Review before applying.")
        
        # Preview tabs
        preview_tabs = st.tabs(["Contacts", "Items", "Vendor-Item Relationships"])
        
        with preview_tabs[0]:
            st.subheader(f"Generated Contacts ({len(preview_data['contacts'])})")

            # Convert to DataFrame for display
            contact_data = []  # Create a list to hold contact records
            for contact in preview_data['contacts']:  # Iterate through the contacts list
                contact_data.append({
                    "Name": contact['name'],
                    "Account Number": contact['xero_account_number'],
                    "Xero Contact ID": contact['xero_contact_id'],
                    "Payment Terms": format_payment_terms(contact.get('payment_terms', 'Net 30 days'))
                })
            
            contact_df = pd.DataFrame(contact_data)  # Create DataFrame from list of dictionaries
            st.dataframe(contact_df, width="stretch", hide_index=True)
        
        with preview_tabs[1]:
            st.subheader(f"Generated Items ({len(preview_data['items'])})")
            
            # Convert to DataFrame for display
            item_data = []
            for item in preview_data["items"]:
                item_data.append({
                    "Code": item["code"],
                    "Name": item["name"],
                    "Unit Price": f"${item['unit_price']:.2f}",
                    "Account Code": item["account_code"],
                    "Tax Code": item["tax_code"]
                })
            
            item_df = pd.DataFrame(item_data)
            st.dataframe(item_df, width="stretch", hide_index=True)
        
        with preview_tabs[2]:
            st.subheader(f"Vendor-Item Relationships ({len(preview_data['vendor_items'])})")
            
            # Convert to DataFrame for display
            vi_data = []
            for vi in preview_data["vendor_items"]:
                vendor_id = vi["vendor_id"]
                vendor_name = next((c["name"] for c in preview_data["contacts"] if c["id"] == vendor_id), "Unknown")
                
                for item_code in vi["item_codes"]:
                    item_name = next((i["name"] for i in preview_data["items"] if i["code"] == item_code), "Unknown")
                    vi_data.append({
                        "Vendor": vendor_name,
                        "Vendor ID": vendor_id,
                        "Item Code": item_code,
                        "Item Name": item_name
                    })
            
            vi_df = pd.DataFrame(vi_data)
            st.dataframe(vi_df, width="stretch", hide_index=True)
        
        # Action buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ Start Over", key="start_over"):
                st.session_state.preview_data = None
                st.session_state.generation_step = "input"
                st.rerun()
        
        with col2:
            override_msg = "Replace existing data" if st.session_state.override_existing else "Add to existing data"
            if st.button(f"✅ Apply Changes ({override_msg})", key="apply_changes"):
                st.session_state.generation_step = "applying"
                st.rerun()
    
    # Applying step - show progress of each step
    elif st.session_state.generation_step == "applying":
        st.info("Applying changes to Xero and catalog files...")
        
        # Create progress container
        progress_container = st.container()
        
        # Run the apply process
        with st.spinner("Please wait while changes are being applied..."):
            if st.session_state.generation_results is None:
                # Initialize progress
                progress_container.text("Starting process...")
                
                # Run the apply function
                results = asyncio.run(apply_synthetic_data(
                    st.session_state.preview_data, 
                    override_existing=st.session_state.override_existing
                ))
                
                # Store results
                st.session_state.generation_results = results
                st.session_state.generation_step = "complete"
                
                # Force rerun to show complete state
                st.rerun()
    
    # Complete step - show results and summary
    elif st.session_state.generation_step == "complete":
        results = st.session_state.generation_results
        
        if results and results.get("success", False):
            st.success("✅ Data generation completed successfully!")
            
            # Show summary
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Contacts Created", results.get("contacts_created", 0))
            with col2:
                st.metric("Items Created", results.get("items_created", 0))
            with col3:
                st.metric("Vendor-Item Relationships", results.get("vendor_items_created", 0))
            
            # Show detailed steps
            st.subheader("Process Steps")
            for step in results.get("steps", []):
                if step["status"] == "complete":
                    st.success(f"✅ {step['name']}" + (f" ({step.get('count', '')})" if "count" in step else ""))
                elif step["status"] == "error":
                    st.error(f"❌ {step['name']}: {step.get('error', 'Unknown error')}")
                else:
                    st.info(f"⏳ {step['name']}")
        else:
            st.error("❌ Data generation failed")
            if "error" in results:
                st.error(f"Error: {results['error']}")
            
            # Show detailed steps that were completed
            st.subheader("Process Steps")
            for step in results.get("steps", []):
                if step["status"] == "complete":
                    st.success(f"✅ {step['name']}")
                elif step["status"] == "error":
                    st.error(f"❌ {step['name']}: {step.get('error', 'Unknown error')}")
                else:
                    st.info(f"⏳ {step['name']}")
        
        # Button to start over
        if st.button("Start New Generation", key="new_generation"):
            st.session_state.preview_data = None
            st.session_state.generation_results = None
            st.session_state.generation_step = "input"
            st.rerun()
    
    # Backup and restore section
    st.divider()
    st.subheader("Backup & Restore")
    
    backup_col1, backup_col2 = st.columns(2)
    
    with backup_col1:
        with st.form("backup_form"):
            st.info("Create a backup of the current catalog data")
            backup_reason = st.text_input("Backup Reason (optional)",
                                         placeholder="e.g., pre_release, milestone_v1")
            
            backup_button = st.form_submit_button("Create Backup")
            
            if backup_button:
                backup_path = backup_catalogs(reason=backup_reason if backup_reason else "manual_backup")
                st.success(f"Catalogs backed up to: {Path(backup_path).name}")
                time.sleep(1)
                st.rerun()
    
    with backup_col2:
        # List existing backups and provide restore option
        backups = list_backups()
        
        if backups:
            with st.form("restore_form"):
                st.info("Restore from a previous backup")
                
                # Format backup options
                backup_options = [f"{b.get('display_name', b['name'])}" for b in backups]
                selected_backup = st.selectbox("Select Backup", options=backup_options)
                
                # Add option to backup current before restoring
                backup_before_restore = st.checkbox("Backup current data before restoring", value=True)
                
                restore_button = st.form_submit_button("Restore Selected Backup")
                
                if restore_button:
                    with st.spinner("Restoring catalogs..."):
                        # Create backup if requested
                        if backup_before_restore:
                            backup_catalogs(reason="before_restore")
                        
                        # Find the backup by display name
                        selected_idx = backup_options.index(selected_backup)
                        if selected_idx >= 0 and selected_idx < len(backups):
                            success = restore_catalogs(backups[selected_idx]["path"])
                            
                            if success:
                                st.success("Catalogs restored successfully!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("Failed to restore catalogs.")
        else:
            st.info("No backups available. Create a backup first.")


def main() -> None:
    st.set_page_config(page_title="Catalogs", layout="wide")
    st.title("Catalogs")
    
    # Create tabs for browsing and management
    browse_tab, manage_tab = st.tabs(["Browse Catalogs", "Manage Catalogs"])
    
    # Fix items.yaml file if needed
    fix_items_yaml(settings.data_dir)
    
    # Load catalogs after fix
    cat = load_catalogs(settings.data_dir)
    
    with browse_tab:
        vendors_tab, items_tab, mapping_tab = st.tabs([
            "Vendors",
            "Items",
            "Vendor-Item Mapping",
        ])

        with vendors_tab:
            st.subheader("Vendor Catalog")
            df_vendors = format_vendor_data(cat.vendors)
            
            # Add search/filter capabilities
            search_vendor = st.text_input("Search vendors by name")
            if search_vendor:
                df_vendors = df_vendors[
                    df_vendors['Vendor Name'].str.contains(search_vendor, case=False)
                ]
            
            st.dataframe(
                df_vendors,
                width="stretch",
                hide_index=True,
            )
            
            # Show vendor statistics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Vendors", len(cat.vendors))
            with col2:
                st.metric(
                    "Active Suppliers",
                    len([v for v in cat.vendors if v.is_supplier])
                )

        with items_tab:
            st.subheader("Item Catalog")
            df_items = format_item_data(cat.items)
            
            # Add price range filter
            col1, col2 = st.columns(2)
            with col1:
                search_item = st.text_input("Search items by name or code")
            with col2:
                show_tax_codes = st.checkbox("Show tax codes", value=False)
            
            if search_item:
                mask = (
                    df_items['Item Name'].str.contains(search_item, case=False) |
                    df_items['Item Code'].str.contains(search_item, case=False)
                )
                df_items = df_items[mask]
                
            if not show_tax_codes:
                df_items = df_items.drop('Tax Code', axis=1)
                
            st.dataframe(
                df_items,
                width="stretch",
                hide_index=True,
            )
            
            # Show item statistics
            st.metric("Total Items", len(cat.items))

        with mapping_tab:
            st.subheader("Vendor-Item Relationships")
            df_mapping = format_vendor_items(cat)
            
            # Add filtering capabilities
            col1, col2 = st.columns(2)
            with col1:
                search_mapping = st.text_input("Search by vendor or item")
            with col2:
                sort_by = st.selectbox(
                    "Sort by",
                    ["Vendor Name", "Item Name"],
                    index=0
                )
                
            if search_mapping:
                mask = (
                    df_mapping['Vendor Name'].str.contains(search_mapping, case=False) |
                    df_mapping['Item Name'].str.contains(search_mapping, case=False)
                )
                df_mapping = df_mapping[mask]
                
            df_mapping = df_mapping.sort_values(sort_by)
            
            st.dataframe(
                df_mapping,
                width="stretch",
                hide_index=True,
            )
            
            # Show relationship statistics
            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "Total Relationships",
                    sum(len(codes) for codes in cat.vendor_items.values())
                )
            with col2:
                st.metric(
                    "Vendors with Items",
                    len(cat.vendor_items)
                )
    
    with manage_tab:
        render_data_generation_ui()


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

