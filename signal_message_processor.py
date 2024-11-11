#!/usr/bin/env python3

import json
import os
import sqlite3
import subprocess
import base64
import time
import mimetypes
import logging
import argparse

# Configure logging
logger = logging.getLogger(__name__)

def setup_logging(log_level):
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    logging.basicConfig(level=numeric_level, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_file):
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_file}")
        exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in config file: {config_file}")
        exit(1)

def get_extension_from_content_type(content_type):
    # Guess the file extension from the content type
    extension = mimetypes.guess_extension(content_type)
    return extension if extension else ''

def main():
    parser = argparse.ArgumentParser(description='Signal Message Processor')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help='Set the logging level (default: INFO)')
    parser.add_argument('--config', default='config.json', help='Path to the configuration file (default: config.json)')
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Load configuration
    config = load_config(args.config)

    attachment_dir = config.get("attachmentDirectory", "attachments")
    db_path = config.get("database", "messages.db")
    phone_number = config.get("phoneNumber")

    if not phone_number:
        logger.error("Phone number not specified in the configuration file")
        exit(1)

    os.makedirs(attachment_dir, exist_ok=True)

    # Ensure the database and schema are created
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        sourceName TEXT,
        timestamp INTEGER,
        message TEXT,
        groupId TEXT,
        groupName TEXT,
        attachmentPaths TEXT,
        attachmentDescriptions TEXT,
        processedAt INTEGER,
        quoteId INTEGER,
        quoteAuthor TEXT,
        quoteText TEXT
    )
    ''')
    conn.commit()

    logger.info("Starting signal-cli subprocess")
    # Start signal-cli subprocess
    signal_cli_process = subprocess.Popen(
        ['signal-cli', '-a', phone_number, 'jsonRpc'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    pending_attachments = {}  # Map from request_id to {'message_id': ..., 'attachment_id': ...}

    try:
        while True:
            line = signal_cli_process.stdout.readline()
            if not line:
                break  # EOF
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON: {line}")
                continue

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Received message: {json.dumps(message)}")

            if message.get('method') == 'receive':
                # Process the incoming message
                process_incoming_message(message, signal_cli_process.stdin, pending_attachments, conn, cursor, attachment_dir)
            elif 'id' in message:
                # This is a response to an attachment request
                request_id = message.get('id')
                process_attachment_response(message, request_id, pending_attachments, conn, cursor, attachment_dir)
            else:
                logger.warning(f"Unknown message type: {message}")

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if signal_cli_process.returncode is None:
            signal_cli_process.terminate()
            signal_cli_process.wait()
        conn.close()

def process_incoming_message(message, stdin, pending_attachments, conn, cursor, attachment_dir):
    try:
        envelope = message.get('params', {}).get('envelope', {})
        dataMessage = envelope.get('dataMessage', {})
        if not dataMessage:
            return  # Ignore delivery receipts and non-content messages

        groupInfo = dataMessage.get('groupInfo')
        if not groupInfo:
            return  # Ignore non-group messages

        message_text = dataMessage.get('message')
        attachments = dataMessage.get('attachments', [])

        if not message_text and not attachments:
            return  # Ignore messages without text or attachments

        source = envelope.get('source')
        sourceName = envelope.get('sourceName')
        timestamp = envelope.get('timestamp')
        groupId = groupInfo.get('groupId')
        groupName = groupInfo.get('groupName')

        # Extract quote information
        quote = dataMessage.get('quote')
        quote_id = None
        quote_author = None
        quote_text = None
        if quote:
            quote_id = quote.get('id')
            quote_author = quote.get('author')
            quote_text = quote.get('text')

        # Insert the message into the database without attachments
        cursor.execute('''
        INSERT INTO messages (source, sourceName, timestamp, message, groupId, groupName, attachmentPaths, attachmentDescriptions, processedAt, quoteId, quoteAuthor, quoteText)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            source, sourceName, timestamp, message_text, groupId, groupName,
            json.dumps([]), '', None, quote_id, quote_author, quote_text
        ))
        conn.commit()
        message_id = cursor.lastrowid

        logger.info(f"Saved message from {source} in group {groupName} with id {message_id}")

        # If there are attachments, request to download them
        for attachment in attachments:
            attachment_id = attachment.get('id')
            # Generate a unique request_id
            request_id = str(int(time.time() * 1000)) + str(attachment_id)
            request = {
                "jsonrpc": "2.0",
                "method": "getAttachment",
                "params": {
                    "id": attachment_id,
                    "groupId": groupId
                },
                "id": request_id
            }

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Sending RPC request: {json.dumps(request)}")

            # Write request to stdin
            stdin.write(json.dumps(request) + '\n')
            stdin.flush()

            # Add to pending attachments
            pending_attachments[request_id] = {
                'message_id': message_id,
                'attachment_id': attachment_id
            }

    except Exception as e:
        logger.exception(f"Error processing message: {e}")

def process_attachment_response(message, request_id, pending_attachments, conn, cursor, attachment_dir):
    try:
        if request_id not in pending_attachments:
            logger.error(f"Received response for unknown request id {request_id}")
            return

        pending_info = pending_attachments.pop(request_id)
        message_id = pending_info['message_id']
        attachment_id = pending_info['attachment_id']

        result = message.get('result')
        if result:
            attachment_data_base64 = result.get('data')
            content_type = result.get('contentType', 'application/octet-stream')

            if attachment_data_base64:
                attachment_data = base64.b64decode(attachment_data_base64)

                # Use the original filename if it has an extension, otherwise use the attachment_id
                if '.' in attachment_id:
                    file_name = attachment_id
                else:
                    file_extension = get_extension_from_content_type(content_type)
                    file_name = f"{attachment_id}{file_extension}"

                file_path = os.path.join(attachment_dir, file_name)
                with open(file_path, 'wb') as f:
                    f.write(attachment_data)

                logger.info(f"Downloaded attachment {attachment_id} to {file_path}")

                # Update the message in the database with the attachment path
                cursor.execute('SELECT attachmentPaths FROM messages WHERE id=?', (message_id,))
                row = cursor.fetchone()
                if row:
                    attachmentPaths = json.loads(row[0]) if row[0] else []
                    attachmentPaths.append(file_path)
                    cursor.execute('UPDATE messages SET attachmentPaths=? WHERE id=?', (json.dumps(attachmentPaths), message_id))
                    conn.commit()
                    logger.info(f"Updated message {message_id} with attachment {file_path}")
                else:
                    logger.error(f"Message id {message_id} not found in database")

            else:
                logger.error(f"No data in attachment response for request id {request_id}")
        else:
            logger.error(f"Failed to download attachment {attachment_id}: No result in response")

    except Exception as e:
        logger.exception(f"Error processing attachment response: {e}")

if __name__ == "__main__":
    main()
