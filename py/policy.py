# A simple singleton class to hold policy parameters for code generation

from yoparse import block_inst

class Policy():
    registered_rams = True      # IMPLEMENTED
    registered_wen = True       # TODO NOT IMPLEMENTED
    # Force unrolled blocks in generate-for loops to be memory-aligned when "rolled up"
    aligned_for_loops = True
    # TODO - Test if it works with aligned_for_loops = False

    @staticmethod
    def flatten_instance_label(label):
        """Combine the information of generate branch name, loop_index, and instance name
        into one flattened name.  This is a matter of personal preference, but needs to
        be agreed upon."""
        branch, instance, loop_index = block_inst(label)
        if branch is None:
            return label
        if loop_index is None:
            return f"{branch}_{instance}"
        return f"{branch}_{loop_index}_{instance}"

    @classmethod
    def flatten_hierarchy(cls, hierarchy):
        hierarchy = list(hierarchy)
        for n in range(len(hierarchy)):
            hierarchy[n] = cls.flatten_instance_label(hierarchy[n])
        return ".".join(hierarchy)

