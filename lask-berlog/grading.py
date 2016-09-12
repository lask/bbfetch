import re
import sys
sys.path += ['/home/lask/Documents/bbfetch']
import blackboard.grading


class Grading(blackboard.grading.Grading):
    username = '20103173'
    course = '_56503_1'
    classes = ['DA3', 'DA6']

    def get_attempt_directory_name(self, attempt):
        """
        Return a path to the directory in which to store files
        relating to the given handin.
        """

        name = attempt.student.name
        class_name = self.get_student_group_display(attempt.student)
        attempt_id = attempt.id
        if attempt_id.startswith('_'):
            attempt_id = attempt_id[1:]
        if attempt_id.endswith('_1'):
            attempt_id = attempt_id[:-2]

        return '{base}/{class_name}/{assignment}/{name}_{id}'.format(
            base='/home/lask/Documents/undervisning/16q1berlog',
            class_name=class_name,
            assignment=self.get_assignment_name_display(attempt.assignment),
            name=name, id=attempt_id)

    def get_student_group_display(self, student):
        groups = self.get_student_groups(student)
        if groups:
            # The students in this course are in at most one Blackboard group,
            # which is just their class.
            return groups[0].name
        else:
            return ""

    def get_group_name_display(self, group_name):
        """Given a group name, compute an abbreviation of the name."""
        if group_name is None:
            return '?'
        elif group_name.startswith('Gruppe'):
            x = group_name.split()
            return '%s-%s' % (x[1], x[3])
        else:
            return group_name

    def get_student_ordering(self, student):
        """
        Return a sorting key for the student
        indicating how students should be sorted when displayed.
        Typically you want to sort by group, then by name.
        """
        return (self.get_student_group_display(student), student.name)

    def get_assignment_name_display(self, assignment):
        """
        Return an abbreviation of the name of an assignment.
        """
        return re.sub(r'Week (\d+) handin', r'\1', assignment.name)

    def get_feedback_score(self, comments):
        """
        Decide from the contents of comments.txt what score to give a handin.
        """
        rehandin = re.search(r'Genaflevering.', comments, re.I)
        accept = re.search(r'Godkendt.', comments, re.I)
        if rehandin and accept:
            raise ValueError("Both rehandin and accept")
        elif rehandin:
            return 0
        elif accept:
            return 1


if __name__ == "__main__":
    Grading.execute_from_command_line()
