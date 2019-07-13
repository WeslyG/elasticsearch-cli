def get_color(data):
    '''
    Return string green then data = 0, and red then data > 0
    '''
    # TODO: try - catch on not int data
    number = int(data)
    if number > 0:
        return 'red'
    elif number == 0:
        return 'green'
    else:
        return False
