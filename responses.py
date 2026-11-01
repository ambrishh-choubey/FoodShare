"""Consistent JSON response envelope used by the API.

Success: {"success": true,  "data": ..., "message": "...", "meta": {...}}
Error:   {"success": false, "error": {"code": "...", "message": "..."}}
"""
from flask import jsonify


def ok(data=None, message=None, status=200, **meta):
    body = {"success": True, "data": data}
    if message:
        body["message"] = message
    if meta:
        body["meta"] = meta
    return jsonify(body), status


def fail(code, message, status=400):
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status
