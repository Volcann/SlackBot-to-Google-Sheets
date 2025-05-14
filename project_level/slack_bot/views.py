# views.py
import json
import logging
import pandas as pd
import re, math
import gspread
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

from slack_bot.utils import (
    extract_yesterday_tasks,
    extract_today_tasks,
    extract_blocker_tasks,
    extract_yesterday_time_spent,
    extract_today_time_spent,
    extract_yesterday_total_time,
    clean_text,
    standardize_time,
    clean_time_column,
    clean_double_ss,
    get_gspread_client
)

logger = logging.getLogger(__name__)

slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)
verifier     = SignatureVerifier(signing_secret=settings.SLACK_SIGNING_SECRET)
MY_USER_ID   = settings.MY_USER_ID

from datetime import datetime, timedelta, date

def member_messages(request, user_id):
    """
    Show all messages in CHANNEL_ID by a single user,
    labeled as Today’s Report, Yesterday’s Report, or exact date,
    and include a collapse to view raw text.
    """
    # 1) Fetch history
    try:
        hist = slack_client.conversations_history(channel=settings.CHANNEL_ID)
        raw = hist.get("messages", [])
    except SlackApiError as e:
        logger.error(f"Slack API error: {e.response['error']}")
        raw = []

    # 2) Compute today/yesterday
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 3) Build list with labels and raw text
    user_msgs = []
    for idx, msg in enumerate(raw):
        if msg.get("user") != user_id:
            continue

        ts = msg.get("ts")
        msg_dt = datetime.fromtimestamp(float(ts)) if ts else None
        msg_date = msg_dt.date() if msg_dt else None

        # Choose label
        if msg_date == today:
            label = "Today’s Report"
        elif msg_date == yesterday:
            label = "Yesterday’s Report"
        else:
            label = msg_date.strftime("%Y-%m-%d") if msg_date else "Unknown Date"

        user_msgs.append({
            "id": f"msg-{idx}",
            "label": label,
            "raw_text": msg.get("text", ""),
        })

    # 4) Fetch profile
    try:
        pr = slack_client.users_profile_get(user=user_id)["profile"]
        name = pr.get("real_name") or f"<@{user_id}>"
        avatar = pr.get("image_192") or pr.get("image_72")
    except SlackApiError:
        name, avatar = f"<@{user_id}>", None

    # 5) Render
    return render(request, "slack_messages/member_messages.html", {
        "user_name": name,
        "user_avatar": avatar,
        "messages": user_msgs,
    })

def pmo_report(request):
    """
    PMO report view: header, per‐user message counts and blocker indicator.
    """
    try:
        hist = slack_client.conversations_history(channel=settings.CHANNEL_ID)
        raw  = hist.get("messages", [])
    except SlackApiError as e:
        logger.error(f"Slack API error: {e.response['error']}")
        raw = []

    users = {}
    total_blockers = 0
    # loop through all messages
    for msg in raw:
        user_id = msg.get("user")
        if not user_id:
            continue

        # extract blocker tasks
        blockers = extract_blocker_tasks(msg.get("text", ""))
        if blockers and not all(b.strip().upper() == "N/A" for b in blockers):
            total_blockers += 1

        # if first time seeing this user, fetch profile
        if user_id not in users:
            try:
                pr = slack_client.users_profile_get(user=user_id)["profile"]
                avatar = pr.get("image_192") or pr.get("image_72")
                name   = pr.get("real_name") or f"<@{user_id}>"
            except SlackApiError:
                avatar = None
                name   = f"<@{user_id}>"
            users[user_id] = {
                "avatar": avatar,
                "name": name,
                "slack_id": user_id,
                "count": 0,
            }

        users[user_id]["count"] += 1

    # turn into list sorted by message count desc
    members = sorted(users.values(), key=lambda x: x["count"], reverse=True)

    return render(request, "slack_messages/pmo_report.html", {
        "members": members,
        "total_blockers": total_blockers,
    })

def get_slack_messages(request):
    messages = []
    error    = None
    warn_missing = False

    try:
        hist = slack_client.conversations_history(channel=settings.CHANNEL_ID)
        raw  = hist.get("messages", [])
    except SlackApiError as e:
        error = f"Slack API error: {e.response['error']}"
        raw   = []

    # Try to get channel name once
    try:
        ci           = slack_client.conversations_info(channel=settings.CHANNEL_ID)
        channel_name = ci["channel"]["name"]
    except SlackApiError as e:
        channel_name = settings.CHANNEL_ID
        if e.response["error"] == "missing_scope":
            warn_missing = True

    for msg in raw:
        user_id = msg.get("user")
        msg["channel_name"] = channel_name

        # enrich profile
        try:
            pr    = slack_client.users_profile_get(user=user_id)["profile"]
            msg["user_avatar"] = pr.get("image_192") or pr.get("image_72")
            msg["user_name"]   = pr.get("real_name") or f"<@{user_id}>"
        except SlackApiError as e:
            if e.response["error"] == "missing_scope":
                warn_missing = True
            # fallback
            msg["user_avatar"] = None
            msg["user_name"]   = f"<@{user_id}>"
        messages.append(msg)

    return render(request, "slack_messages/messages.html", {
        "messages":     messages,
        "error":        error,
        "warn_missing": warn_missing,
    })

def get_slack_messages_html(request):
    messages = []
    error = None
    warn_missing = False

    try:
        hist = slack_client.conversations_history(channel=settings.CHANNEL_ID)
        raw = hist.get("messages", [])
    except SlackApiError as e:
        error = f"Slack API error: {e.response['error']}"
        raw = []

    try:
        ci = slack_client.conversations_info(channel=settings.CHANNEL_ID)
    except SlackApiError as e:
        if e.response["error"] == "missing_scope":
            warn_missing = True

    for msg in raw:
        user_id = msg.get("user")
        ts = msg.get("ts")
        data = msg.get("text")
        readable_time = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S") if ts else None

        enriched_msg = {
            "data": data,
            "time": readable_time,
        }

        try:
            pr = slack_client.users_profile_get(user=user_id)["profile"]
            enriched_msg["user_name"] = pr.get("real_name") or f"<@{user_id}>"
        except SlackApiError as e:
            if e.response["error"] == "missing_scope":
                warn_missing = True

            enriched_msg["user_name"] = f"<@{user_id}>"

        messages.append(enriched_msg)

    messy_csv = pd.DataFrame(messages)
    df_html = messy_csv.to_html(classes="table table-bordered table-striped", index=False, escape=False)

    # Use correct column name
    messy_csv['Yesterday’s tasks'] = messy_csv["data"].apply(extract_yesterday_tasks)
    messy_csv['Today’s tasks'] = messy_csv["data"].apply(extract_today_tasks)
    messy_csv['Blocker'] = messy_csv["data"].apply(extract_blocker_tasks)
    messy_csv['Yesterday task time'] = messy_csv["data"].apply(extract_yesterday_time_spent)
    messy_csv['Today task time'] = messy_csv["data"].apply(extract_today_time_spent)

    # If you want the extracted tasks as a single string per row:
    messy_csv['Yesterday’s tasks'] = messy_csv["data"].apply(
        lambda x: "\n".join(extract_yesterday_tasks(x))
    )
    messy_csv['Today’s tasks'] = messy_csv["data"].apply(
        lambda x: "\n".join(extract_today_tasks(x))
    )
    messy_csv['Blocker'] = messy_csv["data"].apply(
        lambda x: "\n".join(extract_blocker_tasks(x))
    )
    messy_csv['Yesterday task time'] = messy_csv["data"].apply(
        lambda x: "\n".join(extract_yesterday_time_spent(x))
    )
    messy_csv['Today task time'] = messy_csv["data"].apply(
        lambda x: "\n".join(extract_today_time_spent(x))
    )

    # Applying the function
    messy_csv['Yesterday Total Time (hrs)'] = messy_csv['Yesterday task time'].apply(extract_yesterday_total_time)

    cols_to_drop = ["data"]
    messy_csv = messy_csv.drop(columns=[col for col in cols_to_drop if col in messy_csv.columns])

    # Standardizing column names
    messy_csv.columns = messy_csv.columns.str.strip()  # Remove leading/trailing spaces
    messy_csv.columns = messy_csv.columns.str.replace("’", "'", regex=True)  # Replace curly apostrophe with straight one
    messy_csv.columns = messy_csv.columns.str.replace("\u00a0", " ", regex=True)  # Remove non-breaking spaces

    # Now apply your functions
    messy_csv["Yesterday's tasks"] = messy_csv["Yesterday's tasks"].apply(clean_text)
    messy_csv["Today's tasks"] = messy_csv["Today's tasks"].apply(clean_text)
    messy_csv["Blocker"] = messy_csv["Blocker"].apply(clean_text)
    messy_csv["Yesterday task time"] = messy_csv["Yesterday task time"].apply(standardize_time)
    messy_csv["Today task time"] = messy_csv["Today task time"].apply(standardize_time)
    messy_csv["Yesterday Total Time (hrs)"] = messy_csv["Yesterday Total Time (hrs)"].apply(standardize_time)

    # Apply the cleaning function
    messy_csv["Yesterday task time"] = messy_csv["Yesterday task time"].apply(clean_time_column)
    messy_csv["Today task time"] = messy_csv["Today task time"].apply(clean_time_column)

    # Apply the cleaning function
    messy_csv["Yesterday task time"] = messy_csv["Yesterday task time"].apply(clean_double_ss)
    messy_csv["Today task time"] = messy_csv["Today task time"].apply(clean_double_ss)
    messy_csv["Yesterday Total Time (hrs)"] = messy_csv["Yesterday Total Time (hrs)"].apply(clean_double_ss)

    gc = get_gspread_client()
    worksheet = gc.open_by_key(settings.GS_SHEET_KEY )
    current_sheet = worksheet.worksheet(settings.GS_WORKSHEET_NAME)

    # Convert DataFrame to list of lists (including headers)
    data = [messy_csv.columns.tolist()] + messy_csv.values.tolist()

    # Update the Google Sheet
    current_sheet.update('A1', data)

    print("Data successfully written to Google Sheets!")

    return render(request, "slack_messages/messages_table.html", {
        "df_html": df_html,
        "error": error,
        "warn_missing": warn_missing,
    })