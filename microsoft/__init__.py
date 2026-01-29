"""
Microsoft Excel Online Sync Module for CSR Breaktime
Provides real-time sync to Excel Online via Microsoft Graph API.
"""

from .excel_handler import ExcelHandler, get_excel_handler

__all__ = ['ExcelHandler', 'get_excel_handler']
