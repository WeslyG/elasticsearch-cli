def name_validator(data):
    '''
    accept only all primaries new_primaries none
    '''
    try:
        if data == 'all' or data == 'primaries' or data == 'new_primaries' or data == 'none':
            return data
        elif data == 'disable':
            return 'none'
        elif data == 'enable':
            return 'all'
        elif data =='default':
            return None
        else:
            raise ValueError
    except ValueError:
        return "Bad status value"
