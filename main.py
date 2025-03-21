from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Union

from mistralai import Mistral
from mistralai import DocumentURLChunk, ImageURLChunk, TextChunk
from youtube_transcript_api import YouTubeTranscriptApi

from urllib.parse import urlparse
from urllib.parse import parse_qs
from pathlib import Path
import urllib.request
import json
import yaml
import os

from dotenv import load_dotenv

load_dotenv()

api_key = os.environ['MISTRAL_API_KEY']
print(api_key)
client = Mistral(api_key=api_key)

# processed_pdf_url = client.ocr.process(
#     document=(
#         "type": "document_url",
#         "document_url": url
#     ),
#     purpose="ocr",
# )

# response_dict = json.loads(pdf_response.model_dump_json())
# print(response_dict['pages'][0])

# Specify model
# model = "mistral-small-latest"
# model="pixtral-12b-latest"

# Define the messages for the chat
# messages = [
#     {
#         "role": "user",
#         "content": [
#             {
#                 "type": "text",
#                 "text": "What text is highlighted on the first page?"
#             },
#             {
#                 "type": "document_url",
#                 "document_url": signed_url.url
#             }
#         ]
#     }
# ]

# Get the chat response
# chat_response = client.chat.complete(
#     model=model,
#     messages=messages
# )

# Print the content of the response
# print(chat_response.choices[0].message.content)

app = FastAPI()

class Submission(BaseModel):
    title: str
    url: str

def get_video_transcript(url):
    parsed_url = urlparse(url)
    video_id = parse_qs(parsed_url.query)['v'][0]

    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    transcript_text = ""

    for transcript_item in transcript:
        transcript_text += transcript_item['text']
        transcript_text += ' '

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Give me the 10 most important points from the text. Return the result as an array in a json string."
                },
                {
                    "type": "text",
                    "text": transcript_text
                }
            ]
        }
    ]
    chat_response = client.chat.complete(
        model="mistral-large-latest",
        messages=messages
    )
    raw_result = chat_response.choices[0].message.content

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Here's the 10 most important points from the video transcript: \n{raw_result} \nAttach the starting timestamp of these points from the transcript json, and return the result in yaml."
                },
                {
                    "type": "text",
                    "text": json.dumps(transcript)
                },
            ]
        }
    ]
    chat_response = client.chat.complete(
        model="codestral-latest",
        messages=messages
    )
    raw_response = chat_response.choices[0].message.content
    response_yaml = "\n".join(raw_response.split('\n')[1:-1])

    print(response_yaml)
    return response_yaml


# Download pdf locally (~/.kai/pdfs/)
# Read pdf blob and upload to Mistral
# Return uploaded PDF id
def download_pdf(title, url):
    file_name = '_'.join(title.split(' ')).lower()
    file_path = Path(f"{Path.home()}/.kai/pdfs/{file_name}.pdf")
    if not os.path.exists(file_path):
        print('File does not exist, downloading')
        urllib.request.urlretrieve(url, file_path)

    print('Uploading file to mistral')
    uploaded_pdf = client.files.upload(
        file={
            "file_name": file_name,
            "content": open(file_path, "rb"),
        },
        purpose="ocr"
    )
    return uploaded_pdf.id


def serve_pdf(file_name):
    file_path = Path(f"{Path.home()}/.kai/pdfs/{file_name}.pdf")
    if not os.path.exists(file_path):
        print('File does not exist')
        return nil

    return FileResponse(file_path, media_type="application/pdf", filename=file_path)


def get_pdf_highlights(doc_id):
    signed_url = client.files.get_signed_url(file_id=doc_id)

    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed_url.url,
        }
    )

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Read all the pages content and give me the 15 most important technical points, along with their page numbers in a json array format."
                },
                {
                    "type": "text",
                    "text": json.dumps(ocr_response.model_dump_json())
                }
            ]
        }
    ]
    chat_response = client.chat.complete(
        model="mistral-large-latest",
        messages=messages
    )
    raw_result = chat_response.choices[0].message.content

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Here's the 15 most important points from the document: \n{raw_result} \nAttach the starting page of these points from the document json, and return the result in yaml. The yaml key for the point should be 'text', and for the page it should be 'page'."
                },
                {
                    "type": "document_url",
                    "document_url": signed_url.url
                }
            ]
        }
    ]
    chat_response = client.chat.complete(
        model="codestral-latest",
        messages=messages
    )
    raw_response = chat_response.choices[0].message.content
    response_yaml = "\n".join(raw_response.split('\n')[1:-1])

    return response_yaml


@app.get("/")
def hello():
    return {"Hello": "World"}

@app.get("/serve/pdf/{file_name}")
def get_pdf_blob(file_name: str):
    return serve_pdf(file_name)

@app.post("/submission/pdf")
def get_pdf_contents(submission: Submission):
    pdf_id = download_pdf(submission.title, submission.url)
    highlights = get_pdf_highlights(pdf_id)
    return highlights

@app.post("/submission/youtube")
def get_youtube_transcript(submission: Submission):
    transcript = get_video_transcript(submission.url)
    return transcript
