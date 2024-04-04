import smtplib
import argparse
import requests
import os
import time
import json
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor


DROPBOX_ERROR_CODE = 1
ZAPIER_ERROR_CODE = 2
TEMPLATE_ERROR_CODE = 3
CHANGES_ERROR_CODE = 4
OUTPUT_FILE_PARSING_ERROR = 5


ZAPIER_SEND_DATA = {
    'to': None,
    'subject': None,
    'body': None
}
links = {}

# Send the email
# server.send_message(msg)

def bytes_to_str(val, fractional=1):
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    mult = 1024
    idx = 0
    while val >= mult:
        val /= mult
        idx += 1
    return ("{0:." + str(fractional) + "f} {1}").format(val, suffixes[idx])

def upload_to_dropbox(target_file_name, source_file, dropbox_token, dropbox_folder):
    '''Upload file to dropbox
    
    Args:
        target_file_name (str): Uploaded file will be rename to this file name.
        source_file (str): File that is going to be uploaded.
        dropbox_token (str): Dropbox API key.
        dropbox_folder (str): Dropbox target folder.

    Returns:
        str: Shared url for download.
    '''
    dropbox_path = '/{folder}/{file_name}'.format(folder=dropbox_folder, file_name=target_file_name)
    DROPBOX_UPLOAD_ARGS['path'] = dropbox_path
    DROPBOX_SHARE_DATA['path'] = dropbox_path
    DROPBOX_DELETE_DATA['path'] = dropbox_path

    # Try to delete the file before upload
    # It's possible to overwrite but this way is cleaner
    headers = {'Authorization': 'Bearer ' + dropbox_token,
            'Content-Type': 'application/json'}
    
    requests.post(DROPBOX_DELETE_URL, data=json.dumps(DROPBOX_DELETE_DATA), headers=headers)

    headers = {'Authorization': 'Bearer ' + dropbox_token,
               'Dropbox-API-Arg': json.dumps(DROPBOX_UPLOAD_ARGS),
               'Content-Type': 'application/octet-stream'}

    # Upload the file
    r = requests.post(DROPBOX_UPLOAD_URL, data=open(source_file, 'rb'), headers=headers)

    if r.status_code != requests.codes.ok:
        print("Failed: upload file to Dropbox: {errcode}".format(errcode=r.status_code))
        return None

    headers = {'Authorization': 'Bearer ' + dropbox_token,
               'Content-Type': 'application/json'}

    # Share and return downloadable url
    r = requests.post(DROPBOX_SHARE_URL, data=json.dumps(DROPBOX_SHARE_DATA), headers=headers)

    if r.status_code != requests.codes.ok:
        print("Failed: get share link from Dropbox {errcode}".format(errcode=r.status_code))
        return None

    # Replace the '0' at the end of the url with '1' for direct download
    return re.sub('dl=.*', 'raw=1', r.json()['url'])

def upload_to_diawi(source_file,token):
    multipart_encoder = MultipartEncoder(fields={
            "token": token,
            "wall_of_apps": "0",
            "find_by_udid": "0",
            "file": (source_file, open(source_file, 'rb'), 'application/octet-stream'),
        })
    events = 0
    def upload_callback(monitor):
            nonlocal events
            events += 1
            if events % 10 == 0:
                print("\r{0:>9s} / {1:9s} [{2:2.0f}%]".format(
                        bytes_to_str(monitor.bytes_read),
                        bytes_to_str(monitor.len),
                        monitor.bytes_read / monitor.len * 100), end='', flush=True)
    multipart_encoder_monitor = MultipartEncoderMonitor(multipart_encoder, upload_callback)
    resp = requests.post("https://upload.diawi.com",
                             data=multipart_encoder_monitor,
                             headers={'Content-Type': multipart_encoder.content_type})
    js = resp.json()
    if 'job' not in js:
        print("Failed: upload file to Diawi")
        return None
    job_id = js["job"]
    print("Uploaded, processing...")
    while True:
            # Poll the status of the job
            if(job_id):
                resp = requests.get("https://upload.diawi.com/status",
                                    params={"token": token, "job": job_id})
                data = resp.json()
                msg = data["message"]
                if msg == "Ok":
                    links['qrcode'] = data["qrcode"]
                    links['link'] = data["link"]
                    break
                time.sleep(1)   
    return links
def get_app(release_dir):
    output_path = os.path.join(release_dir, 'output-metadata.json')
    with(open(output_path)) as app_output:
        json_data = json.load(app_output)
    apk_details_key = ''
    if(json_data['elements'][0]):
        apk_details_key = json_data['elements'][0]
    else:
        return None, None   
    app_version = apk_details_key['versionName']
    app_file = os.path.join(release_dir, apk_details_key['outputFile'])
    return app_version, app_file


def get_changes(change_log_path):
    '''Extract latest changes from changelog file.
    Changes are separated by ##

    Args:
        change_log_path (str): Path to changelog file.

    Returns:
        str: Latest changes.
    '''
    print("change_log_path")
    with(open(change_log_path)) as change_log_file:
        change_log = change_log_file.read()

    # Split by '##' and remove lines starting with '#'
    latest_version_changes = change_log.split('##')[0][:-1]
    latest_version_changes = re.sub('^#.*\n?', '', latest_version_changes, flags=re.MULTILINE)

    return latest_version_changes

def get_email(app_name, app_version, links, changes, template_file_path):
    '''Use template file to create release email subject and title.

    Args:
        app_name (str): App name.
        app_version (str): App version.
        app_url (str): Url for app download.
        changes (str): Lastest app changelog.
        template_file_path (str): Path to template file.

    Returns:
        (str, str): Email subject and email body.
    '''
    print()
    target_subject = 1
    target_body = 2
    target = 0
    subject = ''
    body = ''

    template = ''
    # String to Html wapper for email
    parts = changes.strip().split('\n\n')
    desired_string = ""
    for part in parts:
        desired_string += "<p>" + part.replace('\n', '</p>\n<p>') + "</p>\n"

    with(open(template_file_path)) as template_file:
        # Open template file and replace placeholders with data
        template = template_file.read().format(
            app_download_url=links['link'],
            app_logo_url=links['qrcode'],
            change_log=desired_string,
            app_name=app_name,
            app_version=app_version
        )
        
    # Iterate over each line and collect lines marked for subject/body
    for line in template.splitlines():
        if line.startswith('#'):
            if line.startswith('#subject'):
                target = target_subject
            elif line.startswith('#body'):
                target = target_body
        else:
            if target == target_subject:
                subject += line + '\n'
            elif target == target_body:
                body += line + '\n'
    
    return subject.rstrip(), body.rstrip()


def send_email(to, subject, body,gmail_user,gmail_password):


    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(gmail_user, gmail_password)

    # # Create a message
    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = to
    msg['Subject'] = subject

    # Add body to the email
    msg.attach(MIMEText(body, 'html'))
    r =  server.send_message(msg)
    if(r == {}):
        print("Success: send email")
        return True 

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--release.dir', dest='release_dir', help='path to release folder', required=True)
    parser.add_argument('--changelog.file', dest='changelog_file', help='path to changelog file', required=True)
    parser.add_argument('--template.file', dest='template_file', help='path to email template file', required=True)
    parser.add_argument('--email.to', dest='email_to', help='email recipients', required=True)
    parser.add_argument('--gmail.user', dest='gmail_user', help='gmail_user recipients', required=True)
    parser.add_argument('--gmail.password', dest='gmail_password', help='gmail_password recipients', required=True)
    parser.add_argument('--diawi.token', dest='diawi_token', help='diawi_token', required=True)
    parser.add_argument('--app.name', dest='app_name', help='app name that will be used as file name', required=True)

    options = parser.parse_args()
    
    # # Extract app version and file
    app_version, app_file = get_app(options.release_dir)
    if app_version == None or app_file == None:
        exit(OUTPUT_FILE_PARSING_ERROR)

    # # Upload app file diawi and get shared url
    links = upload_to_diawi(app_file, options.diawi_token)
    if links == None:
        exit(DROPBOX_ERROR_CODE)


    #  # Extract latest changes
    latest_changes = get_changes(options.changelog_file)
    if latest_changes == None:
        exit(CHANGES_ERROR_CODE)

    #     # Compose email subject and body
    subject, body = get_email(options.app_name, app_version, links, latest_changes, options.template_file)
    if subject == None or body == None:
        exit(TEMPLATE_ERROR_CODE)


    try:
        # Gửi email
        if not send_email(options.email_to, subject, body,options.gmail_user,options.gmail_password):
            exit(ZAPIER_ERROR_CODE)
    except smtplib.SMTPAuthenticationError:
        # Xử lý khi có lỗi xác thực SMTP
        print("Authentication error: Username and Password not accepted.")
        exit(ZAPIER_ERROR_CODE)
    except smtplib.SMTPException as e:
        # Xử lý khi có lỗi SMTP khác
        print("SMTP error:", e)
        exit(ZAPIER_ERROR_CODE)
    except Exception as e:
        # Xử lý các lỗi khác không được xác định trước
        print("An unexpected error occurred:", e)
        exit(ZAPIER_ERROR_CODE)



