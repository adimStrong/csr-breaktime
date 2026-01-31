"""
Create Excel file in OneDrive for CSR Breaktime sync.
Creates a new Excel workbook with a BreakLog table.
"""

import os
import sys
import asyncio
import aiohttp

# Load .env file
from pathlib import Path
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from microsoft.auth import get_access_token, is_configured

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

async def create_excel_file():
    """Create an Excel file in OneDrive root folder."""

    print("=" * 50)
    print("CSR Breaktime - OneDrive Excel Setup")
    print("=" * 50)

    # Check credentials
    if not is_configured():
        print("\nERROR: Microsoft credentials not configured")
        print("Check your .env file has:")
        print("  - MICROSOFT_CLIENT_ID")
        print("  - MICROSOFT_CLIENT_SECRET")
        print("  - MICROSOFT_REFRESH_TOKEN")
        return None

    # Get access token
    print("\n1. Getting access token...")
    token = get_access_token()
    if not token:
        print("ERROR: Failed to get access token")
        print("The refresh token may have expired. Run setup_microsoft_auth.py to get a new one.")
        return None
    print("   OK - Token acquired")

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    async with aiohttp.ClientSession() as session:
        # Create empty Excel file
        print("\n2. Creating Excel file in OneDrive...")

        # Use upload session to create a new empty Excel file
        file_name = "CSR_Breaktime_Log.xlsx"

        # First check if file already exists
        search_url = f"{GRAPH_BASE_URL}/me/drive/root/children?$filter=name eq '{file_name}'"
        async with session.get(search_url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get('value'):
                    existing_file = data['value'][0]
                    file_id = existing_file['id']
                    print(f"   File already exists: {file_name}")
                    print(f"   File ID: {file_id}")

                    # Check if table exists
                    print("\n3. Checking for BreakLog table...")
                    table_url = f"{GRAPH_BASE_URL}/me/drive/items/{file_id}/workbook/tables/BreakLog"
                    async with session.get(table_url, headers=headers) as table_resp:
                        if table_resp.status == 200:
                            print("   Table 'BreakLog' already exists!")
                            print("\n" + "=" * 50)
                            print("SUCCESS! Add this to your .env file:")
                            print(f"EXCEL_FILE_ID={file_id}")
                            print("=" * 50)
                            return file_id
                        else:
                            print("   Table not found, will create it...")

                    # Create the table
                    return await create_table_in_file(session, headers, file_id)

        # Create new file by uploading empty Excel template
        # We'll create a minimal xlsx file
        print("   Creating new file...")

        # Create file using simple upload
        create_url = f"{GRAPH_BASE_URL}/me/drive/root:/{file_name}:/content"

        # Create a minimal Excel file (we'll add content after)
        # For now, upload an empty file placeholder
        empty_content = b''

        # Use the workbook create endpoint instead
        create_folder_url = f"{GRAPH_BASE_URL}/me/drive/root/children"
        file_data = {
            "name": file_name,
            "file": {},
            "@microsoft.graph.conflictBehavior": "replace"
        }

        # Actually, we need to create via a different method
        # Let's use the Excel workbook session create

        # First create an empty file
        async with session.put(
            create_url,
            headers={**headers, 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
            data=create_minimal_xlsx()
        ) as resp:
            if resp.status in (200, 201):
                file_info = await resp.json()
                file_id = file_info['id']
                print(f"   File created: {file_name}")
                print(f"   File ID: {file_id}")
            else:
                error = await resp.text()
                print(f"   ERROR creating file: {resp.status}")
                print(f"   {error}")
                return None

        # Wait a moment for the file to be ready
        await asyncio.sleep(2)

        # Create the table
        return await create_table_in_file(session, headers, file_id)


async def create_table_in_file(session, headers, file_id):
    """Create the BreakLog table in the Excel file."""

    print("\n3. Setting up worksheet data...")

    # First, add headers to the worksheet
    # We need to set the range with header data first
    headers_data = [
        ["Timestamp", "User ID", "Username", "Full Name", "Break Type", "Action", "Duration", "Reason"]
    ]

    range_url = f"{GRAPH_BASE_URL}/me/drive/items/{file_id}/workbook/worksheets/Sheet1/range(address='A1:H1')"
    async with session.patch(range_url, headers=headers, json={"values": headers_data}) as resp:
        if resp.status in (200, 201):
            print("   Headers added to worksheet")
        else:
            error = await resp.text()
            print(f"   Warning: Could not set headers: {error}")

    await asyncio.sleep(1)

    print("\n4. Creating BreakLog table...")

    # Create a table from the range
    table_url = f"{GRAPH_BASE_URL}/me/drive/items/{file_id}/workbook/tables/add"
    table_data = {
        "address": "Sheet1!A1:H1",
        "hasHeaders": True
    }

    async with session.post(table_url, headers=headers, json=table_data) as resp:
        if resp.status in (200, 201):
            table_info = await resp.json()
            table_id = table_info.get('id', 'unknown')
            print(f"   Table created with ID: {table_id}")
        else:
            error = await resp.text()
            print(f"   ERROR creating table: {resp.status}")
            print(f"   {error}")
            # Try alternative method - maybe table already exists

    # Rename the table to BreakLog
    print("\n5. Renaming table to 'BreakLog'...")

    # Get the table that was just created (usually Table1)
    tables_url = f"{GRAPH_BASE_URL}/me/drive/items/{file_id}/workbook/tables"
    async with session.get(tables_url, headers=headers) as resp:
        if resp.status == 200:
            tables = await resp.json()
            if tables.get('value'):
                table = tables['value'][0]
                table_name = table['name']

                # Rename to BreakLog
                rename_url = f"{GRAPH_BASE_URL}/me/drive/items/{file_id}/workbook/tables/{table_name}"
                async with session.patch(rename_url, headers=headers, json={"name": "BreakLog"}) as rename_resp:
                    if rename_resp.status == 200:
                        print("   Table renamed to 'BreakLog'")
                    else:
                        print(f"   Could not rename table (may already be named BreakLog)")

    print("\n" + "=" * 50)
    print("SUCCESS! Add this to your .env file:")
    print(f"EXCEL_FILE_ID={file_id}")
    print("=" * 50)

    return file_id


def create_minimal_xlsx():
    """Create a minimal valid xlsx file bytes."""
    import io
    import zipfile

    # A minimal xlsx is a zip file with specific XML files
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml
        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''
        zf.writestr('[Content_Types].xml', content_types)

        # _rels/.rels
        rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
        zf.writestr('_rels/.rels', rels)

        # xl/workbook.xml
        workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>'''
        zf.writestr('xl/workbook.xml', workbook)

        # xl/_rels/workbook.xml.rels
        wb_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        zf.writestr('xl/_rels/workbook.xml.rels', wb_rels)

        # xl/worksheets/sheet1.xml
        sheet = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData/>
</worksheet>'''
        zf.writestr('xl/worksheets/sheet1.xml', sheet)

    buffer.seek(0)
    return buffer.read()


if __name__ == '__main__':
    result = asyncio.run(create_excel_file())
    if result:
        print(f"\nFile ID: {result}")
    else:
        print("\nSetup failed. Check the errors above.")
