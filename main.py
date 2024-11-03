import base64
import datetime
import json
import logging
import os

import requests
import re
import random

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauth2client.service_account import ServiceAccountCredentials

from constants import SCOPES, BIRTHDAY, GEBURTSTAG, GERMAN, ENGLISH, \
    GERMAN_MESSAGES, ENGLISH_MESSAGES


load_dotenv()

logging.basicConfig(level=logging.INFO)

CALENDAR_ID = os.getenv("CALENDAR_ID")
if not CALENDAR_ID:
    raise Exception("Environment variable CALENDAR_ID not set.")


def get_service_account_keyfile_from_env():
    """
    Expects a env variable SERVICE_ACCOUNT_CREDENTIALS with the base64 encoded service account credentials.
    Obtain these by downloading the credentials.json file for the Google Cloud service account and running:
        cat credentials.json | base64 | pbcopy
    and then pasting the output into the env variable.
    """
    base64_data = os.getenv("SERVICE_ACCOUNT_CREDENTIALS")
    if not base64_data:
        raise Exception("No service account credentials found in environment.")
    return json.loads(base64.b64decode(base64_data).decode("utf-8"))


def get_credential():
    credential = ServiceAccountCredentials.from_json_keyfile_dict(
        get_service_account_keyfile_from_env(), SCOPES
    )
    if not credential or credential.invalid:
        raise Exception("Unable to authenticate using service account key.")
    return credential


def get_upcoming_events(creds: ServiceAccountCredentials):
    try:
        service = build("calendar", "v3", credentials=creds)

        # Call the Calendar API
        now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
        events_result = (
            service.events()
            .list(
                calendarId=CALENDAR_ID,
                timeMin=now,
                maxResults=30,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            print("No upcoming events found.")
            return []

        return events

    except HttpError as error:
        print(f"An error occurred: {error}")


def birthday_event(event):
    summary = event.get("summary", "")
    full_name = re.sub(fr"(?i)({GEBURTSTAG}|{BIRTHDAY})", "", summary).strip()
    return {
        "full_name": full_name,
        "first_name": full_name.split(" ")[0],
        "start": event["start"].get("dateTime", event["start"].get("date")),
        "language": GERMAN if GEBURTSTAG in summary.lower() else ENGLISH,
        "days_until_event": days_until_birthday(event),
    }


def days_until_birthday(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    start_date = datetime.datetime.fromisoformat(start).date()
    current_date = datetime.date.today()
    return (start_date - current_date).days


def filter_birthdays(events: list, days_in_advance=3):
    birthdays = []
    for event in events:
        summary = event.get("summary", "").lower()

        # Skip if not a birthday event
        if GEBURTSTAG not in summary and BIRTHDAY not in summary:
            continue

        # Skip if more than three days in the future
        if days_until_birthday(event) > days_in_advance:
            continue

        # Add to birthdays
        birthdays.append(birthday_event(event))

    return birthdays


def compile_message(birthday):
    language = birthday["language"]
    first_name = birthday["first_name"]
    message_set = ENGLISH_MESSAGES if language == ENGLISH else GERMAN_MESSAGES
    raw_message = random.choice(message_set)
    message = raw_message.format(first_name=first_name)
    return message


def generate_output(birthdays) -> str:
    output = []
    today_birthdays = [b for b in birthdays if b["days_until_event"] == 0]
    upcoming_birthdays = [b for b in birthdays if b["days_until_event"] > 0]
    if len(today_birthdays) == 0:
        output.append("No birthdays today.\n")
    else:
        output.append(f"Birthdays today: {len(today_birthdays)}\n")
        for birthday in today_birthdays:
            output.append(birthday["full_name"])
            # todo: Temporarily disabled, since the ntfy app doesn't let me copy
            #  these messages to the clipboard, so there's no point in sending them.
            # output.append(compile_message(birthday))
        output.append("")

    if len(upcoming_birthdays) == 0:
        output.append("No upcoming birthdays.")

    else:
        output.append(f"Upcoming birthdays:")
        for birthday in upcoming_birthdays:
            output.append(f"{birthday['start']} - {birthday['full_name']}")

    return "\n".join(output)


def get_title(birthdays):
    return f"You have {len(birthdays)} upcoming birthdays!"


def send_message(message, title):
    requests.post(
        "https://ntfy.sh/ljp-birthday-reminder",
        data=message,
        headers={
            "Title": title,
            "Priority": "urgent",
            "Tags": "balloon"
        }
    )
    logging.info(f"Sent message.")


def main():
    creds = get_credential()
    events = get_upcoming_events(creds)
    birthdays = filter_birthdays(events)
    if len(birthdays) == 0:
        logging.info("No upcoming birthdays found. Exiting.")
        return
    output = generate_output(birthdays)
    title = get_title(birthdays)
    send_message(output, title)


if __name__ == "__main__":
    main()
