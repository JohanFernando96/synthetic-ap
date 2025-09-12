from __future__ import annotations
import uuid
import json 
import yaml
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional
from openai import OpenAI
from pydantic import ValidationError

from ..config.settings import settings
from ..config.runtime_config import load_runtime_config
from .schema import (
    SyntheticContactRequest,
    SyntheticContactData,
    SyntheticItemData,
    SyntheticVendorItemRelation
)
from ..xero.client import get_contacts, create_contacts

# Set up logger
logger = logging.getLogger(__name__)

def fix_contact_structure(contact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fix contact structure to match Xero API requirements.
    Converts single-string Address and Phone to proper structured objects.
    """
    fixed_contact = dict(contact)  # Create a copy to avoid modifying the original
    
    # Remove fields that shouldn't go to Xero
    fields_to_remove = [
        "IsSupplier",
        "BusinessType",
        "PaymentTerms",
        "__metadata" 
    ]
    for field in fields_to_remove:
        if field in fixed_contact:
            fixed_contact.pop(field)
    
    # Fix Address - should be an array of Address objects
    if "Address" in fixed_contact:
        address_str = fixed_contact.pop("Address")
        
        # Try to parse address components if possible
        address_parts = address_str.split(',')
        address_line1 = address_parts[0].strip() if len(address_parts) > 0 else address_str
        
        city = ""
        region = ""
        postal_code = ""
        country = "Australia"
        
        # Try to extract more details if available
        if len(address_parts) > 1:
            location_parts = address_parts[-1].strip().split()
            if len(location_parts) >= 2 and location_parts[-1].isdigit():
                postal_code = location_parts[-1]
                region = location_parts[-2] if len(location_parts) >= 2 else ""
                if len(address_parts) >= 2:
                    city = address_parts[-2].strip()
        
        # Create address objects, only including non-empty fields
        street_address = {
            "AddressType": "STREET",
            "AddressLine1": address_line1,
            "Country": country
        }
        
        # Only add non-empty fields
        if city:
            street_address["City"] = city
        if region:
            street_address["Region"] = region
        if postal_code:
            street_address["PostalCode"] = postal_code
            
        # Create PO Box address (copy of street address but with different type)
        pobox_address = street_address.copy()
        pobox_address["AddressType"] = "POBOX"
        
        fixed_contact["Addresses"] = [street_address, pobox_address]
    
    # Fix Phone - should be an array of Phone objects
    if "Phone" in fixed_contact:
        phone_str = fixed_contact.pop("Phone")
        
        # Try to parse phone number components
        phone_number = phone_str.replace(" ", "").replace("-", "").replace("+61", "0")
        
        # Extract area code and number if possible
        phone_country_code = ""
        phone_area_code = ""
        phone_number_part = phone_number
        
        if phone_str.startswith("+61"):
            phone_country_code = "61"
            # Remove leading 0 if present after +61
            if phone_number.startswith("0"):
                phone_number_part = phone_number[1:]
                
        # Extract area code (2, 3, 4, etc. for different AU regions)
        if len(phone_number_part) > 2:
            phone_area_code = phone_number_part[0:1]
            phone_number_part = phone_number_part[1:]
        
        fixed_contact["Phones"] = [
            {
                "PhoneType": "DEFAULT",
                "PhoneCountryCode": phone_country_code,
                "PhoneAreaCode": phone_area_code,
                "PhoneNumber": phone_number_part
            }
        ]
    
    # Ensure proper ContactPersons array if missing
    if "ContactPersons" not in fixed_contact:
        fixed_contact["ContactPersons"] = []
        
    # Remove BatchPayments if it's empty
    if "BatchPayments" in fixed_contact and not fixed_contact["BatchPayments"]:
        fixed_contact.pop("BatchPayments")
    
    return fixed_contact

async def generate_contact_data(industry: str, count: int) -> List[Dict[str, Any]]:
    """Generate realistic Australian business contact data using LLM."""
    cfg = load_runtime_config(settings.data_dir)
    oai = OpenAI(api_key=settings.openai_api_key)
    
    system = (
        "You are a synthetic data generator for Australian businesses, specializing in accounts payable scenarios. "
        "Generate realistic supplier/vendor contacts that would typically supply goods or services to a company "
        "in the specified industry. Each contact should be a legitimate business that provides relevant "
        "products or services that a company in this industry would regularly purchase from.\n\n"
        "Consider:\n"
        "- Industry-specific suppliers and service providers\n"
        "- Common business expenses in the industry\n"
        "- Realistic Australian business names and locations\n"
        "- Appropriate payment terms for the industry\n"
        "Respond with a valid JSON object."
    )
    
    user_prompt = {
        "industry": industry,
        "count": count,
        "region": "Australia",
        "scenario": "accounts_payable",
        "details_required": [
            "Name (realistic business name relevant to industry)",
            "FirstName and LastName (contact person)",
            "EmailAddress (business email)",
            "AccountNumber (in format AN-XXXX)",
            "BankAccountDetails (Australian format BSB-AccountNumber)",
            "TaxNumber (Australian ABN format XX XXX XXX XXX)",
            "Address (realistic Australian address with proper format)",
            "Phone (realistic Australian format)",
            "BatchPayments information (BankAccountName, BankAccountNumber)",
            # Keep these for YAML but they won't be sent to Xero
            "BusinessType (what they supply to the industry)",
            "PaymentTerms (typical for their business type)"
        ],
        "example_format": {
            "Name": "Sydney Steel Suppliers Pty Ltd",
            "FirstName": "Robert",
            "LastName": "Chen",
            "EmailAddress": "accounts@sydneysteel.com.au",
            "AccountNumber": "AN-0123",
            "BusinessType": "Steel and metal products supplier",
            "PaymentTerms": "30 day terms for established customers"
        },
        "output_format": "Please provide the result as a JSON object with a 'Contacts' array"
    }
    
    resp = oai.chat.completions.create(
        model=cfg.ai.model,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Generate industry-specific AP vendor data as JSON for: {json.dumps(user_prompt, indent=2)}"}
        ],
    )
    
    try:
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        contacts = data.get("Contacts", [])
        
        # Store the metadata separately
        contact_metadata = {}
        for contact in contacts:
            account_number = contact.get("AccountNumber")
            if account_number:
                contact_metadata[account_number] = {
                    "business_type": contact.get("BusinessType"),
                    "payment_terms": contact.get("PaymentTerms")
                }
        
        # Fix contact structure for Xero API compatibility
        fixed_contacts = [fix_contact_structure(contact) for contact in contacts]
        logger.info(f"Generated and fixed structure for {len(fixed_contacts)} contacts")
        
        return fixed_contacts, contact_metadata
    except Exception as e:
        logger.error(f"Error generating contact data: {e}")
        return [], {}

async def generate_items_data(industry: str, count: int) -> List[Dict[str, Any]]:
    """Generate realistic industry-specific item data."""
    cfg = load_runtime_config(settings.data_dir)
    oai = OpenAI(api_key=settings.openai_api_key)
    
    system = (
        "You are a synthetic data generator for Australian businesses, specializing in accounts payable scenarios. "
        "Generate realistic items and services that would typically be purchased from suppliers in the specified industry. "
        "Each item should represent a real product or service that companies regularly procure from their vendors.\n\n"
        "Consider:\n"
        "- Common materials and supplies needed in the industry\n"
        "- Regular services that are outsourced\n"
        "- Equipment rental and maintenance\n"
        "- Professional services\n"
        "- Consumables and recurring purchases\n"
        "- Realistic pricing for Australian market\n"
        "Respond with a valid JSON object."
    )
    
    user_prompt = {
        "industry": industry,
        "count": count,
        "region": "Australia",
        "scenario": "accounts_payable",
        "details_required": [
            "id (UUID format)",
            "code (format like IND-XXX where IND is industry abbreviation)",
            "name (detailed product/service name)",
            "description (what this item is used for)",
            "unit_price (realistic AUD price)",
            "typical_quantity (common order quantity)",
            "unit_measure (e.g., each, hours, kg, meters)",
            "account_code (use 453 for inventory items, 469 for rentals, 477 for services)",
            "tax_code (use INPUT for standard GST, EXEMPTEXPENSES for non-GST)",
            "price_variance_pct (use 0.10 for all items)",
            "category (e.g., Materials, Services, Equipment, Consumables)"
        ],
        "example_format": {
            "id": "uuid-string",
            "code": "MIN-001",
            "name": "High-Grade Iron Ore",
            "description": "Premium grade iron ore for steel production",
            "unit_price": 120.50,
            "typical_quantity": 1000,
            "unit_measure": "tonnes",
            "category": "Raw Materials"
        },
        "output_format": "Please provide the result as a JSON object with an 'Items' array"
    }
    
    resp = oai.chat.completions.create(
        model=cfg.ai.model,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Generate industry-specific AP purchase items as JSON for: {json.dumps(user_prompt, indent=2)}"}
        ],
    )
    
    try:
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        items_data = data.get("Items", [])
        
        # Process items to ensure they match our schema
        processed_items = []
        for item in items_data:
            # Determine account code based on category
            category = item.get("category", "").lower()
            account_code = "453"  # default for inventory items
            if "service" in category:
                account_code = "477"
            elif "rental" in category or "hire" in category:
                account_code = "469"
            
            processed_item = {
                "id": item.get("id", str(uuid.uuid4())),
                "code": item.get("code"),
                "name": item.get("name"),
                "unit_price": float(item.get("unit_price", 100.0)),
                "account_code": str(account_code),
                "tax_code": item.get("tax_code", "INPUT"),
                "price_variance_pct": float(item.get("price_variance_pct", 0.10))
            }
            processed_items.append(processed_item)
        
        return processed_items
    except Exception as e:
        logger.error(f"Error generating item data: {e}")
        return []

def save_yaml(data: Dict[str, Any], path: Path) -> None:
    """Save data to a YAML file with UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def load_yaml(path: Path) -> Dict[str, Any]:
    """Load data from a YAML file with UTF-8 encoding."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

async def process_synthetic_data_generation(request: SyntheticContactRequest) -> Dict[str, Any]:
    """Process the synthetic data generation flow."""
    # 1. Generate synthetic contacts data for Xero
    xero_contacts_payload = await generate_contact_data(request.industry, request.num_contacts)
    
    # 2. Call Xero to create contacts
    creation_response = await create_contacts(xero_contacts_payload)
    created_contacts = creation_response.get("Contacts", [])
    
    # 3. Get all contacts to ensure we have the IDs
    xero_contacts_response = await get_contacts()
    all_contacts = xero_contacts_response.get("Contacts", [])
    
    # 4. Create vendor entries for YAML
    vendor_entries = []
    account_number_to_id = {}
    
    # Build lookup map of AccountNumber to ContactID
    for contact in all_contacts:
        if contact.get("AccountNumber") and contact.get("ContactID"):
            account_number_to_id[contact.get("AccountNumber")] = contact.get("ContactID")
    
    # Create vendor entries with Xero IDs
    for contact in xero_contacts_payload:
        account_number = contact.get("AccountNumber")
        xero_contact_id = account_number_to_id.get(account_number)
        
        if not xero_contact_id:
            logger.warning(f"Could not find Xero ID for contact with AccountNumber {account_number}")
            continue
            
        vendor_id = f"VEND-{account_number.replace('AN-', '')}"
        vendor_entry = {
            "id": vendor_id,
            "name": contact.get("Name"),
            "xero_contact_id": xero_contact_id,
            "xero_account_number": account_number,
            # "is_supplier": True,
            "payment_terms": {"type": "DAYSAFTERBILLDATE", "days": 30}
        }
        vendor_entries.append(vendor_entry)
    
    # 5. Generate items data
    items_data = await generate_items_data(request.industry, request.num_contacts * request.items_per_vendor)
    item_entries = []
    
    for item in items_data:
        # Generate UUID if not present
        if not item.get("id"):
            item["id"] = str(uuid.uuid4())
            
        # Ensure account_code is a string
        account_code = item.get("account_code", "453")
        if not isinstance(account_code, str):
            account_code = str(account_code)
            
        item_entries.append({
            "id": item.get("id"),
            "code": item.get("code"),
            "name": item.get("name"),
            "unit_price": float(item.get("unit_price", 100.0)),
                        "account_code": account_code,  # Now ensured to be a string
            "tax_code": item.get("tax_code", "INPUT"),
            "price_variance_pct": float(item.get("price_variance_pct", 0.10))
        })
    
    # 6. Create vendor-item relationships
    vendor_item_entries = []
    vendor_ids = [v["id"] for v in vendor_entries]
    item_codes = [i["code"] for i in item_entries]
    
    # Assign items to vendors
    for vendor_id in vendor_ids:
        # Select random items for this vendor
        available_codes = item_codes.copy()
        random.shuffle(available_codes)
        
        # Take up to items_per_vendor codes
        selected_codes = available_codes[:request.items_per_vendor]
        
        if selected_codes:
            vendor_item_entries.append({
                "vendor_id": vendor_id,
                "item_codes": selected_codes
            })
    
    # 7. Update YAML files
    catalogs_dir = Path(settings.data_dir) / "catalogs"
    
    # Update vendors.yaml
    vendors_path = catalogs_dir / "vendors.yaml"
    vendors_data = load_yaml(vendors_path)
    if not vendors_data:
        vendors_data = {"vendors": []}
    
    # Add new vendors to existing data
    vendors_data["vendors"].extend(vendor_entries)
    save_yaml(vendors_data, vendors_path)
    
    # Update items.yaml
    items_path = catalogs_dir / "items.yaml"
    items_data = load_yaml(items_path)
    if not items_data:
        items_data = {"items": []}
    
    # Add new items to existing data
    items_data["items"].extend(item_entries)
    save_yaml(items_data, items_path)
    
    # Update vendor_items.yaml
    vi_path = catalogs_dir / "vendor_items.yaml"
    vi_data = load_yaml(vi_path)
    if not vi_data:
        vi_data = {"vendor_items": []}
    
    # Add new vendor-item relationships to existing data
    vi_data["vendor_items"].extend(vendor_item_entries)
    save_yaml(vi_data, vi_path)
    
    return {
        "contacts": vendor_entries,
        "items": item_entries,
        "vendor_items": vendor_item_entries
    }

# Add to src/synthap/ai/synthgen.py

async def preview_synthetic_data(request: SyntheticContactRequest) -> Dict[str, Any]:
    """Generate synthetic data for preview without saving to Xero or YAML files."""
    # 1. Generate industry-specific synthetic contacts data
    xero_contacts_payload, contact_metadata = await generate_contact_data(request.industry, request.num_contacts)
    
    # 2. Create sample vendor entries (without Xero IDs yet)
    vendor_entries = []
    
    for i, contact in enumerate(xero_contacts_payload):
        account_number = contact.get("AccountNumber")
        vendor_id = f"VEND-{account_number.replace('AN-', '')}" if account_number else f"VEND-{request.industry[:3].upper()}{i+1:03d}"
        
        # Get metadata for this contact
        metadata = contact_metadata.get(account_number, {})
        payment_terms = metadata.get("payment_terms", "Net 30 days")
        
        # Convert payment terms string to structured format
        payment_terms_dict = {"type": "DAYSAFTERBILLDATE", "days": 30}  # default
        if isinstance(payment_terms, str):
            if "net" in payment_terms.lower():
                try:
                    days = int(''.join(filter(str.isdigit, payment_terms)))
                    payment_terms_dict = {"type": "DAYSAFTERBILLDATE", "days": days}
                except ValueError:
                    pass
        
        vendor_entry = {
            "id": vendor_id,
            "name": contact.get("Name", f"{request.industry} Vendor {i+1}"),
            "xero_contact_id": "(Will be assigned after creation)",
            "xero_account_number": account_number or f"AN-{i+1:04d}",
            "payment_terms": payment_terms_dict
        }
        vendor_entries.append(vendor_entry)
    
    # 3. Generate industry-specific items data
    items_data = await generate_items_data(request.industry, request.num_contacts * request.items_per_vendor)
    item_entries = []
    
    for item in items_data:
        # Generate UUID if not present
        if not item.get("id"):
            item["id"] = str(uuid.uuid4())
            
        # Ensure account_code is a string
        account_code = item.get("account_code", "453")
        if not isinstance(account_code, str):
            account_code = str(account_code)
            
        item_entries.append({
            "id": item.get("id"),
            "code": item.get("code"),
            "name": item.get("name"),
            "unit_price": float(item.get("unit_price", 100.0)),
            "account_code": account_code,
            "tax_code": item.get("tax_code", "INPUT"),
            "price_variance_pct": float(item.get("price_variance_pct", 0.10))
        })
    
    # 4. Create vendor-item relationships
    vendor_item_entries = []
    vendor_ids = [v["id"] for v in vendor_entries]
    item_codes = [i["code"] for i in item_entries]
    
    # Assign items to vendors more intelligently based on industry
    for i, vendor_id in enumerate(vendor_ids):
        # Take a slice of items for this vendor, ensuring each vendor gets some unique items
        start_idx = (i * request.items_per_vendor) % len(item_codes)
        selected_codes = [item_codes[j % len(item_codes)] for j in range(start_idx, start_idx + request.items_per_vendor)]
        
        if selected_codes:
            vendor_item_entries.append({
                "vendor_id": vendor_id,
                "item_codes": selected_codes
            })
    
    # 5. Return preview data
    return {
        "raw_contacts": xero_contacts_payload,  # Original format for Xero API
        "contact_metadata": contact_metadata,   # Store metadata separately
        "contacts": vendor_entries,             # YAML format
        "items": item_entries,                  # YAML format
        "vendor_items": vendor_item_entries     # YAML format
    }

def ensure_yaml_file(path: Path, key: str) -> None:
    """Ensure a YAML file exists with the proper structure."""
    if not path.exists() or path.stat().st_size == 0:
        with open(path, 'w', encoding='utf-8') as f:
            yaml.safe_dump({key: []}, f)

def ensure_catalog_files(base_dir: str = None) -> None:
    """Ensure all catalog YAML files exist with proper structure."""
    base_dir = base_dir or settings.data_dir
    catalogs_dir = Path(base_dir) / "catalogs"
    catalogs_dir.mkdir(parents=True, exist_ok=True)
    
    # Define all required YAML files
    yaml_files = {
        "vendors.yaml": "vendors",
        "items.yaml": "items",
        "vendor_items.yaml": "vendor_items",
    }
    
    # Ensure each file exists with proper structure
    for filename, key in yaml_files.items():
        file_path = catalogs_dir / filename
        ensure_yaml_file(file_path, key)

async def apply_synthetic_data(preview_data: Dict[str, Any], override_existing: bool = False) -> Dict[str, Any]:
    """Apply the previewed synthetic data to Xero and YAML files."""
    results = {
        "steps": [],
        "success": False,
        "contacts_created": 0,
        "items_created": 0,
        "vendor_items_created": 0
    }
    
    try:
        # Ensure YAML files exist
        ensure_catalog_files()
        
        # Get catalog directory path
        catalogs_dir = Path(settings.data_dir) / "catalogs"
        vendors_path = catalogs_dir / "vendors.yaml"
        items_path = catalogs_dir / "items.yaml"
        vi_path = catalogs_dir / "vendor_items.yaml"
        
        # 1. Create contacts in Xero
        results["steps"].append({"name": "Creating contacts in Xero", "status": "running"})
        xero_contacts_payload = preview_data.get("raw_contacts", [])
        
        # Log the payload for debugging
        logger.info(f"Creating {len(xero_contacts_payload)} contacts in Xero")
        logger.debug(f"Xero contacts payload: {json.dumps(xero_contacts_payload, indent=2)}")
        
        creation_response = await create_contacts(xero_contacts_payload)
        created_contacts = creation_response.get("Contacts", [])
        
        # Log the response
        logger.info(f"Xero creation response: {json.dumps(creation_response, indent=2)}")
        
        results["steps"][-1]["status"] = "complete"
        results["steps"][-1]["count"] = len(created_contacts)
        results["contacts_created"] = len(created_contacts)
        
        # Store the account numbers of contacts we just created
        our_account_numbers = {contact.get("AccountNumber") for contact in xero_contacts_payload}
        
        # 2. Get all contacts to ensure we have the IDs
        results["steps"].append({"name": "Retrieving contact IDs from Xero", "status": "running"})
        xero_contacts_response = await get_contacts()
        all_contacts = xero_contacts_response.get("Contacts", [])
        
        # Filter to only get our newly created contacts
        our_contacts = [
            contact for contact in all_contacts 
            if contact.get("AccountNumber") in our_account_numbers
        ]
        
        logger.info(f"Found {len(our_contacts)} matching contacts in Xero")
        results["steps"][-1]["status"] = "complete"
        
        # 3. Update vendor entries with Xero IDs
        results["steps"].append({"name": "Updating vendor entries with Xero IDs", "status": "running"})
        account_number_to_id = {
            contact.get("AccountNumber"): contact.get("ContactID")
            for contact in our_contacts
            if contact.get("AccountNumber") and contact.get("ContactID")
        }
        
        vendor_entries = []
        for contact in preview_data.get("contacts", []):
            account_number = contact.get("xero_account_number")
            xero_contact_id = account_number_to_id.get(account_number)
            
            if not xero_contact_id:
                logger.warning(f"Could not find Xero ID for contact with AccountNumber {account_number}")
                continue
            
            # Get metadata for this contact
            metadata = preview_data.get("contact_metadata", {}).get(account_number, {})
            
            # Ensure payment terms is in the correct format
            payment_terms = contact.get("payment_terms", {"type": "DAYSAFTERBILLDATE", "days": 30})
            if isinstance(payment_terms, str):
                # Convert string payment terms to dictionary format
                days = 30  # default
                if "net" in payment_terms.lower():
                    try:
                        days = int(''.join(filter(str.isdigit, payment_terms)))
                    except ValueError:
                        pass
                payment_terms = {"type": "DAYSAFTERBILLDATE", "days": days}
            
            vendor_entry = {
                "id": contact["id"],
                "name": contact["name"],
                "xero_contact_id": xero_contact_id,
                "xero_account_number": account_number,
                "payment_terms": payment_terms
            }
            vendor_entries.append(vendor_entry)
        
        item_entries = preview_data.get("items", [])
        vendor_item_entries = preview_data.get("vendor_items", [])

        logger.info(f"Processing {len(item_entries)} items and {len(vendor_item_entries)} vendor-item relationships")

        logger.info(f"Updated {len(vendor_entries)} vendors with Xero IDs")
        results["steps"][-1]["status"] = "complete"
        
        # 4. Update YAML files
        results["steps"].append({"name": "Saving to YAML files", "status": "running"})
        catalogs_dir = Path(settings.data_dir) / "catalogs"
        
        # When saving YAML files, ensure they exist first
        ensure_yaml_file(vendors_path, "vendors")
        ensure_yaml_file(items_path, "items")
        ensure_yaml_file(vi_path, "vendor_items")
        
        # Update vendors.yaml
        if override_existing:
            vendors_data = {"vendors": vendor_entries}
        else:
            vendors_data = load_yaml(vendors_path)
            if not vendors_data or "vendors" not in vendors_data:
                vendors_data = {"vendors": []}
            vendors_data["vendors"].extend(vendor_entries)
        
        save_yaml(vendors_data, vendors_path)
        
        # Update items.yaml
        if override_existing:
            items_data = {"items": item_entries}
        else:
            items_data = load_yaml(items_path)
            if not items_data or "items" not in items_data:
                items_data = {"items": []}
            items_data["items"].extend(item_entries)
        
        save_yaml(items_data, items_path)
        
        # Filter out any vendor-item relationships where the vendor ID doesn't exist
        valid_vendor_ids = {v["id"] for v in vendor_entries}
        vendor_item_entries = [
            vi for vi in vendor_item_entries 
            if vi["vendor_id"] in valid_vendor_ids
        ]
        
        if override_existing:
            vi_data = {"vendor_items": vendor_item_entries}
        else:
            vi_data = load_yaml(vi_path)
            if not vi_data or "vendor_items" not in vi_data:
                vi_data = {"vendor_items": []}
            vi_data["vendor_items"].extend(vendor_item_entries)
        
        logger.info(f"Saving {len(vi_data['vendor_items'])} vendor-item relationships to YAML")
        save_yaml(vi_data, vi_path)
        results["vendor_items_created"] = len(vendor_item_entries)
        
        results["steps"][-1]["status"] = "complete"
        results["success"] = True
        
    except Exception as e:
        logger.error(f"Error applying synthetic data: {str(e)}", exc_info=True)
        if results["steps"]:
            results["steps"][-1]["status"] = "error"
            results["steps"][-1]["error"] = str(e)
        results["error"] = str(e)
    
    return results