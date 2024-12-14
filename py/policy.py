# A simple singleton class to hold policy parameters for code generation

class Policy():
    registered_rams = True      # IMPLEMENTED
    registered_wen = True       # TODO NOT IMPLEMENTED
    # Force unrolled blocks in generate-for loops to be memory-aligned when "rolled up"
    aligned_for_loops = False
