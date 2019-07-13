def status_validator(data):
    '''
    accept only json and yaml
    '''
    try:
        if data == 'yellow' or data == 'green' or data == 'red':
            return data
        elif data == 'y':
            return 'yellow'
        elif data == 'r':
            return 'red'
        elif data == 'g':
            return 'green'
        elif data is None:
            return data
        else:
            raise ValueError
    except ValueError:
        return "Bad status value"
