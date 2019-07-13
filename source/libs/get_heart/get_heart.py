def get_heart(status):
    '''
    return emoji hearts on status es
    '''
    if status == "green":
        return "💚"
    elif status == "red":
        return "❤️"
    elif status == "yellow":
        return "💛"
    return False
