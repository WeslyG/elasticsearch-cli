def timeout_validator(data):
    '''
    text to string
    '''
    try:
        if data.isnumeric():
            return str('%ss' % data)
        elif data[:-1].isnumeric() and data[-1] == 's':
            return data
        else:
            raise ValueError
    except ValueError:
        return "Bad timeout value"
