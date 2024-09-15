import cmd
import boto3
import json
import os
import logging
import re
import uuid

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class ConnectCLI(cmd.Cmd):
    intro = 'Welcome to the Amazon Connect CLI tool. Type help or ? to list commands.\n'
    prompt = '(connect-cli) '

    def __init__(self):
        super().__init__()
        self.previous_regions = {}
        self.previous_instance_ids = {}

    def do_download(self, arg):
        'Download a contact flow: download'
        try:
            source_region = self.get_previous_input('source_region', 'Enter source AWS region: ')
            source_instance_id = self.get_previous_input('source_instance_id', 'Enter source instance ID: ')
            contact_flow_id = input('Enter contact flow ID to download: ')

            logging.debug(f"Source Region: {source_region}")
            logging.debug(f"Source Instance ID: {source_instance_id}")
            logging.debug(f"Contact Flow ID: {contact_flow_id}")

            aws_credentials = load_aws_credentials('aws_credentials.json', 'source')
            source_client = get_connect_client(
                source_region,
                aws_credentials['aws_access_key_id'],
                aws_credentials['aws_secret_access_key']
            )

            contact_flow_json = download_contact_flow(source_client, source_instance_id, contact_flow_id)
            with open('contact_flow.json', 'w', encoding='utf-8') as f:
                json.dump(contact_flow_json, f, indent=4, ensure_ascii=False)
            print('Contact flow downloaded and saved to contact_flow.json')

            # Save entered region and instance ID
            self.previous_regions['source_region'] = source_region
            self.previous_instance_ids['source_instance_id'] = source_instance_id

        except Exception as e:
            logging.error(f"Error during download: {e}", exc_info=True)
            print(f"An error occurred during download: {e}")

    def do_upload(self, arg):
        'Upload a contact flow to a new environment: upload'
        try:
            target_region = self.get_previous_input('target_region', 'Enter target AWS region: ')
            target_instance_id = self.get_previous_input('target_instance_id', 'Enter target instance ID: ')
            contact_flow_name = input('Enter name for the new contact flow: ')

            # Valid contact flow types
            valid_contact_flow_types = [
                'CONTACT_FLOW', 'CUSTOMER_QUEUE', 'CUSTOMER_HOLD', 'CUSTOMER_WHISPER',
                'AGENT_HOLD', 'AGENT_WHISPER', 'OUTBOUND_WHISPER',
                'AGENT_TRANSFER', 'QUEUE_TRANSFER'
            ]
            while True:
                contact_flow_type = input('Enter contact flow type (e.g., CONTACT_FLOW): ').strip()
                if not contact_flow_type:
                    contact_flow_type = 'CONTACT_FLOW'  # Default value
                    print('No contact flow type entered. Using default: CONTACT_FLOW')
                    break
                elif contact_flow_type in valid_contact_flow_types:
                    break
                else:
                    print(f'Invalid contact flow type. Valid types are: {", ".join(valid_contact_flow_types)}')
            description = input('Enter description for the new contact flow: ')

            aws_credentials = load_aws_credentials('aws_credentials.json', 'target')
            with open('contact_flow.json', 'r', encoding='utf-8') as f:
                contact_flow_json = json.load(f)

            mapping = load_resource_mapping('resource_mapping.json')
            identifiers = get_resource_identifiers(contact_flow_json)
            missing_identifiers = identifiers - set(mapping.keys())

            if missing_identifiers:
                print('Some resource identifiers are missing in the mapping.')
                mapping_updates = prompt_for_resource_mapping(missing_identifiers)
                mapping.update(mapping_updates)
                save_resource_mapping('resource_mapping.json', mapping)

            modified_contact_flow = replace_resource_identifiers(contact_flow_json, mapping)
            ensure_identifiers_are_uuids(modified_contact_flow)

            target_client = get_connect_client(
                target_region,
                aws_credentials['aws_access_key_id'],
                aws_credentials['aws_secret_access_key']
            )

            existing_contact_flow_id = get_contact_flow_id_by_name(
                target_client, target_instance_id, contact_flow_name
            )

            if existing_contact_flow_id:
                print(f'Contact flow with name "{contact_flow_name}" already exists. Updating it.')
                contact_flow_id = update_contact_flow_content(
                    target_client, target_instance_id, existing_contact_flow_id,
                    modified_contact_flow
                )
                print(f'Contact flow updated. Contact Flow ID: {contact_flow_id}')
            else:
                contact_flow_id = upload_contact_flow(
                    target_client, target_instance_id, contact_flow_name,
                    modified_contact_flow, contact_flow_type, description
                )
                print(f'Contact flow uploaded. New Contact Flow ID: {contact_flow_id}')

            # Save entered region and instance ID
            self.previous_regions['target_region'] = target_region
            self.previous_instance_ids['target_instance_id'] = target_instance_id

        except Exception as e:
            logging.error(f"Error during upload: {e}", exc_info=True)
            print(f"An error occurred during upload: {e}")

    def do_list(self, arg):
        'List all contact flows in a region: list'
        try:
            target_region = self.get_previous_input('target_region', 'Enter target AWS region: ')
            target_instance_id = self.get_previous_input('target_instance_id', 'Enter target instance ID: ')

            aws_credentials = load_aws_credentials('aws_credentials.json', 'target')
            target_client = get_connect_client(
                target_region,
                aws_credentials['aws_access_key_id'],
                aws_credentials['aws_secret_access_key']
            )

            contact_flows = list_contact_flows(target_client, target_instance_id)
            for contact_flow in contact_flows:
                print(f"Contact Flow Name: {contact_flow['Name']}, ID: {contact_flow['Id']}")
        except Exception as e:
            logging.error(f"Error during listing: {e}", exc_info=True)
            print(f"An error occurred during listing: {e}")

    def do_exit(self, arg):
        'Exit the CLI: exit'
        print('Exiting...')
        return True

    def get_previous_input(self, key, prompt_message):
        if key in self.previous_regions:
            return self.previous_regions[key]
        return input(prompt_message)

def list_contact_flows(client, instance_id):
    paginator = client.get_paginator('list_contact_flows')
    contact_flows = []
    for page in paginator.paginate(InstanceId=instance_id):
        contact_flows.extend(page['ContactFlowSummaryList'])
    return contact_flows

def get_connect_client(region_name, aws_access_key_id, aws_secret_access_key):
    return boto3.client(
        'connect',
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )

# Other functions remain unchanged


def download_contact_flow(client, instance_id, contact_flow_id):
    response = client.describe_contact_flow(
        InstanceId=instance_id,
        ContactFlowId=contact_flow_id
    )
    contact_flow_content = response['ContactFlow']['Content']
    contact_flow_json = json.loads(contact_flow_content)
    return contact_flow_json

# Update RESOURCE_IDENTIFIER_KEYS with all possible keys
RESOURCE_IDENTIFIER_KEYS = [
    # Queues
    'QueueId',
    'QueueName',

    # Prompts
    'PromptId',
    'PromptName',

    # Contact Flows
    'FlowId',
    'FlowName',
    'ContactFlowId',
    'ContactFlowName',
    'ContactFlowArn',
    'FlowArn',

    # Lambda Functions
    'LambdaFunctionArn',
    'LambdaFunctionName',
    'FunctionArn',

    # Lex Bots (V1)
    'LexBotName',
    'LexBotAlias',
    'BotName',
    'BotAlias',

    # Lex Bots (V2)
    'LexV2BotId',
    'LexV2BotAliasId',
    'LexV2BotName',
    'LexV2BotAliasName',
    'LexV2LocaleId',

    # S3 Buckets
    'BucketName',
    'S3BucketName',
    'S3Key',

    # Custom Vocabularies
    'VocabularyId',
    'VocabularyName',

    # Kinesis Streams
    'StreamName',
    'StreamArn',

    # Event Sources
    'EventSourceName',

    # Attributes (if referencing external resources)
    'AttributeName',

    # Any other keys that may contain ARNs or resource IDs
    'ResourceId',
    'ResourceArn',

    # Voice IDs (for Amazon Polly)
    'VoiceId',

    # Contact Attributes (if they contain resource references)
    'Value',

    # Other Potential Keys
    'Message',  # If messages contain resource identifiers
    'Filter',   # For EventBridge filters
    'RuleFunctionArn',  # For rule functions
    'DataTableArn',     # For Wisdom or Data tables
]

def get_resource_identifiers(contact_flow_json):
    identifiers = set()
    actions = contact_flow_json.get('Actions', [])
    for action in actions:
        parameters = action.get('Parameters', {})
        ids = extract_resource_identifiers(parameters)
        if ids:
            logging.debug(f"Found resource identifiers in action {action.get('Identifier')}: {ids}")
        identifiers.update(ids)
    return identifiers



def extract_resource_identifiers(data, path=''):
    identifiers = set()
    if isinstance(data, dict):
        for key, value in data.items():
            current_path = f"{path}/{key}" if path else key
            if isinstance(value, str):
                if key in RESOURCE_IDENTIFIER_KEYS or key.lower().endswith(('id', 'arn')):
                    logging.debug(f"Found identifier at path {current_path}: Key = {key}, Value = {value}")
                    identifiers.add(value)
                elif value.startswith('arn:aws:connect'):
                    logging.debug(f"Found ARN at path {current_path}: Value = {value}")
                    identifiers.add(value)
            elif isinstance(value, (dict, list)):
                identifiers.update(extract_resource_identifiers(value, current_path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            current_path = f"{path}[{index}]"
            identifiers.update(extract_resource_identifiers(item, current_path))
    return identifiers



def load_resource_mapping(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
    except FileNotFoundError:
        mapping = {}
    return mapping

def save_resource_mapping(file_path, mapping):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=4, ensure_ascii=False)

def prompt_for_resource_mapping(missing_identifiers):
    mapping_updates = {}
    for identifier in missing_identifiers:
        new_identifier = input(f'Enter new identifier for resource {identifier}: ').strip()
        mapping_updates[identifier] = new_identifier
    return mapping_updates

def replace_resource_identifiers(contact_flow_json, mapping):
    actions = contact_flow_json.get('Actions', [])
    for action in actions:
        parameters = action.get('Parameters', {})
        updated_parameters = replace_identifiers_in_structure(parameters, mapping)
        action['Parameters'] = updated_parameters
    return contact_flow_json


    
def replace_identifiers_in_structure(data, mapping, path=''):
    if isinstance(data, dict):
        updated_data = {}
        for key, value in data.items():
            current_path = f"{path}/{key}" if path else key
            if isinstance(value, (dict, list)):
                updated_data[key] = replace_identifiers_in_structure(value, mapping, current_path)
            elif isinstance(value, str) and value.startswith("arn:"):
                original_value = value.strip()
                new_value = mapping.get(original_value, original_value)
                updated_data[key] = new_value
                if original_value != new_value:
                    logging.debug(f"Replaced value at path {current_path}: {original_value} -> {new_value}")
                else:
                    logging.debug(f"Value at path {current_path} not replaced, no matching mapping for: {original_value}")
            else:
                updated_data[key] = value
        return updated_data
    elif isinstance(data, list):
        return [replace_identifiers_in_structure(item, mapping, f"{path}[{index}]") for index, item in enumerate(data)]
    else:
        return data


def is_valid_uuid(uuid_str):
    regex = re.compile(
        '^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z', re.I)
    return bool(regex.match(uuid_str))

def ensure_identifiers_are_uuids(contact_flow_json):
    try:
        name_to_uuid = {}
        actions = contact_flow_json.get('Actions', [])
        for action in actions:
            identifier = action.get('Identifier')
            if identifier and not is_valid_uuid(identifier):
                new_uuid = str(uuid.uuid4())
                name_to_uuid[identifier] = new_uuid
                action['Identifier'] = new_uuid
        # Update StartAction
        start_action = contact_flow_json.get('StartAction', '')
        if start_action in name_to_uuid:
            contact_flow_json['StartAction'] = name_to_uuid[start_action]
        # Update Transitions recursively
        for action in actions:
            transitions = action.get('Transitions', {})
            updated_transitions = update_identifiers_in_structure(transitions, name_to_uuid)
            action['Transitions'] = updated_transitions
        # Update ActionMetadata
        metadata = contact_flow_json.get('Metadata', {})
        action_metadata = metadata.get('ActionMetadata', {})
        for key in list(action_metadata.keys()):
            if key in name_to_uuid:
                action_metadata[name_to_uuid[key]] = action_metadata.pop(key)
                action_metadata[name_to_uuid[key]]['name'] = key  # Preserve friendly name
        # Save the updated metadata
        contact_flow_json['Metadata']['ActionMetadata'] = action_metadata
    except Exception as e:
        logging.error(f"Error ensuring identifiers are UUIDs: {e}", exc_info=True)
        raise

def update_identifiers_in_structure(data, name_to_uuid):
    if isinstance(data, dict):
        updated_data = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                updated_data[key] = update_identifiers_in_structure(value, name_to_uuid)
            elif isinstance(value, str):
                updated_data[key] = name_to_uuid.get(value, value)
            else:
                updated_data[key] = value
        return updated_data
    elif isinstance(data, list):
        updated_list = []
        for item in data:
            if isinstance(item, (dict, list)):
                updated_list.append(update_identifiers_in_structure(item, name_to_uuid))
            elif isinstance(item, str):
                updated_list.append(name_to_uuid.get(item, item))
            else:
                updated_list.append(item)
        return updated_list
    else:
        return data

def upload_contact_flow(client, instance_id, name, contact_flow_json, contact_flow_type, description=''):
    # Debugging: Write the modified contact flow to a file
    with open('modified_contact_flow_debug.json', 'w', encoding='utf-8') as debug_file:
        json.dump(contact_flow_json, debug_file, indent=4, ensure_ascii=False)

    # Ensure that contact_flow_json is serialized only once
    if isinstance(contact_flow_json, dict):
        content_str = json.dumps(contact_flow_json, ensure_ascii=False)
    elif isinstance(contact_flow_json, str):
        content_str = contact_flow_json
    else:
        raise ValueError("contact_flow_json must be a dict or a JSON string")

    logging.debug(f"Content to be sent to AWS: {content_str[:500]}...")  # Print the first 500 characters for debugging

    response = client.create_contact_flow(
        InstanceId=instance_id,
        Name=name,
        Type=contact_flow_type,
        Description=description,
        Content=content_str
    )
    return response['ContactFlowId']

def update_contact_flow_content(client, instance_id, contact_flow_id, contact_flow_json):
    try:
        # Debugging: Write the modified contact flow to a file
        with open('modified_contact_flow_debug.json', 'w', encoding='utf-8') as debug_file:
            json.dump(contact_flow_json, debug_file, indent=4, ensure_ascii=False)

        # Ensure that contact_flow_json is serialized only once
        if isinstance(contact_flow_json, dict):
            content_str = json.dumps(contact_flow_json, ensure_ascii=False)
        elif isinstance(contact_flow_json, str):
            content_str = contact_flow_json
        else:
            raise ValueError("contact_flow_json must be a dict or a JSON string")

        logging.debug(f"Content to be sent to AWS for update: {content_str[:500]}...")  # Print the first 500 characters for debugging

        response = client.update_contact_flow_content(
            InstanceId=instance_id,
            ContactFlowId=contact_flow_id,
            Content=content_str
        )
        return contact_flow_id
    except client.exceptions.InvalidContactFlowException as e:
        error_message = e.response['Error'].get('Message', '')
        problems = e.response.get('problems', [])
        logging.error(f"InvalidContactFlowException: {error_message}")
        for problem in problems:
            logging.error(problem.get('message', ''))
        print(f"An error occurred during upload: {error_message}")
        for problem in problems:
            print(problem.get('message', ''))
        raise
    except Exception as e:
        logging.error(f"Unexpected error during update: {e}", exc_info=True)
        raise

def get_contact_flow_id_by_name(client, instance_id, name):
    paginator = client.get_paginator('list_contact_flows')
    for page in paginator.paginate(InstanceId=instance_id):
        for contact_flow_summary in page['ContactFlowSummaryList']:
            if contact_flow_summary['Name'] == name:
                return contact_flow_summary['Id']
    return None

def load_aws_credentials(file_path, environment):
    """
    Load AWS credentials from a JSON file for the specified environment ('source' or 'target').
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f'Credentials file {file_path} not found.')

    with open(file_path, 'r', encoding='utf-8') as f:
        credentials = json.load(f)

    if environment not in credentials:
        raise KeyError(f'Environment "{environment}" not found in credentials file.')

    required_keys = ['aws_access_key_id', 'aws_secret_access_key']
    for key in required_keys:
        if key not in credentials[environment]:
            raise KeyError(f'Key "{key}" missing in credentials for environment "{environment}".')

    return credentials[environment]

if __name__ == '__main__':
    ConnectCLI().cmdloop()
