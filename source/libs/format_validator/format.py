def format_validator(data):
    '''
    accept only json and yaml
    '''
    try:
        if data == 'json' or data == 'text':
            return data
        else:
            raise ValueError
    except ValueError:
        return "Bad timeout value"
