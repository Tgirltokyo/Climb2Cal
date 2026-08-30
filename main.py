from datetime import datetime
import json
import sys
import time
from playwright.sync_api import sync_playwright
import os.path
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]
timer = time.time()
global stats
stats = {
    "sessions": 0,
    "added": 0,
    "updated": 0,
    "unchanged": 0
}


def main():
    reach_schedule = get_reach_schedule()
    cal_id = get_google_calendar()
    update_google_calendar(cal_id, reach_schedule)


def get_reach_schedule():
    with sync_playwright() as p:

        #get existing user login, else request login details
        if os.path.exists('login.json'):
            with open('login.json', "r") as file:
                login = json.load(file)
        else:
            login = {"first_name": input("\n\nEnter Your First Name: "),"last_name": input( "Enter Your Surname: "),}
            with open("login.json", "w") as file:
                json.dump(login, file)
        print(f"\nLogging in as: {login['first_name']} {login['last_name']}")

        browser = p.firefox.launch(headless=True)
        page = browser.new_page()
        #login
        page.goto("https://climbinglondon.co.uk/diary/i-login.php")
        attempt = 0
        print("Retrieving Sessions")
        while True:
            attempt += 1
            page.fill("#first", login["first_name"])
            page.fill("#last", login["last_name"])
            page.click('input.art-button[value="Log me in"]')
            page.wait_for_load_state("networkidle")
            check = page.locator('input.art-button[value="All Dates from today"]')
            # check login successfull
            if check.count() > 0:
                #if login successful
                page.click('input.art-button[value="All Dates from today"]')
                page.wait_for_load_state("networkidle")
                button = page.locator("button.xlsx.art-button")
                button_blob = button.get_attribute("data-fileblob")
                data = json.loads(button_blob)
                sessions = data['data']
                return sessions[1:]
            elif attempt < 3:
                #if login unsuccessful
                print("error logging in, trying again")
            else:
                print("error logging in, try deleting 'login.json' then try again")
                sys.exit()


def get_google_calendar():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    print("Retrieving Google Calendar")
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)

        # use the saved calendar ID.
        if os.path.exists('calendar_id'):
            with open('calendar_id.json', "r") as file:
                calendar_id = json.load(file)
            try:
                # check that the calendar still exists
                service.calendars().get(calendarId=calendar_id).execute()
                return calendar_id

            except Exception:
                pass

        # no existing calendar
        print("Calendar 'Climb2Cal' not Found")
        new_cal = service.calendars().insert(body={"summary": "Climb2Cal"}).execute()
        calendar_id = new_cal["id"]
        with open('calendar_id.json', "w") as file:
            json.dump(calendar_id, file)
        print("Calendar 'Climb2Cal' Created")
        return calendar_id

    except HttpError as error:
        print(f"An error occurred: {error}")


def update_google_calendar(ID, sessions):
    print("Updating Google Calendar\n")
    #set up google stuff again
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    service = build("calendar", "v3", credentials=creds)
    #all dates from AND including today
    today = datetime.now(ZoneInfo("Europe/London")).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )
    google_events = service.events().list(
        calendarId=ID,
        timeMin=today.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()["items"]

    sessions.append(None)
    google_events.append(None)
    # prepare fot loop
    current_session = sessions.pop(0)
    current_google_event = google_events.pop(0)
    test_run = 0

    while len(sessions) > 0:
        #returns add, next, delete or update
        task = get_task(current_google_event, current_session)

        #if session is not in calendar ind occurs before next google event
        if task[0] == "add":
            event = {
                'summary': task[1],
                'location': 'The Reach Climbing Wall, Unit 6, Mellish Industrial Estate, Harrington Way, London SE18 5NR, UK',
                'start': {
                    'dateTime': task[2],
                    'timeZone': 'Europe/London',
                },
                'end': {
                    'dateTime': task[3],
                    'timeZone': 'Europe/London',
                },
            }
            service.events().insert(calendarId=ID, body=event).execute()
            print(f"Successfully Added: {task[1]} on {datetime.fromisoformat(task[2])}")

            #prepare next cycle
            current_session = sessions.pop(0)
            stats["added"] += 1

        #if session is already in calendar
        elif task[0] == "next":
            #prepare next cycle
            current_session = sessions.pop(0)
            current_google_event = google_events.pop(0)
            stats["unchanged"] += 1

        #if session occurs after next google event
        elif task[0] == "delete":
            service.events().delete(calendarId=ID, eventId=current_google_event['id']).execute()
            #prepare next cycle
            current_google_event = google_events.pop(0)
            stats["updated"] += 1

        #if session starts at the same time but has a different summary or end time
        elif task[0] == "update":
            #delete current google event
            service.events().delete(calendarId=ID, eventId=current_google_event['id']).execute()\
            #add updated event
            event = {
                'summary': task[1],
                'location': 'The Reach Climbing Wall, Unit 6, Mellish Industrial Estate, Harrington Way, London SE18 5NR, UK',
                'start': {
                    'dateTime': task[2],
                    'timeZone': 'Europe/London',
                },
                'end': {
                    'dateTime': task[3],
                    'timeZone': 'Europe/London',
                },
            }
            service.events().insert(calendarId=ID, body=event).execute()
            print(f"Successfully Updated: {task[1]} on {datetime.fromisoformat(task[2])}")
            #prepare next cycle
            current_session = sessions.pop(0)
            current_google_event = google_events.pop(0)
            stats["updated"] += 1


        #if no valid operation was returned
        else:
            print(f"an error occurred: no valid operation found for {current_session}\n{current_google_event}")


def get_task(google, session):
    start, end = session[1].split(" – ")
    session_start_iso = datetime.strptime(f"{session[0]} {start}",
                                          "%A, %d %b %Y %H:%M").isoformat()
    session_end_iso = datetime.strptime(f"{session[0]} {end}",
                                        "%A, %d %b %Y %H:%M").isoformat()
    session_title = session[2]
    #if there are no more google events, just add sessions
    if google is None:
        return ['add', session_title, session_start_iso, session_end_iso]

    try:
        dt = datetime.fromisoformat(google["start"]["dateTime"])
        dt = dt.astimezone(ZoneInfo(google["start"]["timeZone"]))
        google_start_iso = dt.replace(tzinfo=None).isoformat()

        dt = datetime.fromisoformat(google["end"]["dateTime"])
        dt = dt.astimezone(ZoneInfo(google["end"]["timeZone"]))
        google_end_iso = dt.replace(tzinfo=None).isoformat()

        google_title = google["summary"]

        ##event exists as is
        if session_title == google_title and session_start_iso == google_start_iso and session_end_iso == google_end_iso:
            return ['next']
        ##session needs adding
        elif session_start_iso < google_start_iso:
            return ['add', session_title, session_start_iso, session_end_iso]
        elif session_start_iso > google_start_iso:
            return ['delete', google['id']]
        else:
            return ['update', session_title, session_start_iso, session_end_iso]

    #if the current google event is missing a: title, start time, end time.
    # delete it, it is not meant to be there
    except KeyError:
        return ['delete', google['id']]

main()
print(f"\n\nClimb2Cal Successfully Executed :)"
      f"\n\nadded: {stats["added"]}   "
      f"updated: {stats["updated"]}   "
      f"unchanged: {stats["unchanged"]}"
      f"\nin {time.time()-timer}seconds :3\n\n")
