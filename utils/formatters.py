def format_large_number(number):
    if number >= 1_00_00_000:
        return f"{number/1_00_00_000:.2f} Cr."
    elif number >= 1_00_000:
        return f"{number/1_00_000:.2f} Lac."
    elif number >= 1000:
        return f"{number/1000:.2f} Th."

def format_ratio(value,suffix=""):
    if value is None:
        return "N/A"
    return f"{value:.2f}{suffix}"