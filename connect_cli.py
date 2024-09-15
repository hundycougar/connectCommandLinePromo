

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
