#!python3

import appex, ui
import os
import datetime
from math import ceil, floor
from operator import itemgetter

# Creating the toggl API object
from toggl.TogglPy import Toggl
toggl_api = "fa786d294f27988b9788d799e0822ba2"
toggl = Toggl()
toggl.setAPIKey(toggl_api)

# Creating the Todoist API object
from pytodoist import todoist as Todoist
todoist = Todoist.login('njwfish@gmail.com', 'projects = user.get_projects()')

COLS = 3


class TimerView (ui.View):
    """
    The TimerView Widget is the Toggl Today Widget that should really be in the app, but its even better. This widget
    interfaces with your Todoist account too, allowing you to track the amount of time spent on a given task in
    Todoist. It assumes you have corresponding Labels in Todoist for the projects you have in Toggl (as this is how
    my workflow is setup).

    When you click a timer in the widget, if there are no tasks associated with that Label in Todoist, it start the
    timer. If there are tasks, it opens a series of pages listing all the tasks (8 per page), and allows you to select
    one. If you do, it starts a Toggl timer in the correct project with the description as the content of the task,
    the tags as the Labels of the task, and the Todoist Project of the task.

    The Labels added as tags is set up to exclude 'ing' Labels, as those are my Toggl Labels. All my Toggl projects end
    'ing', to facilitate not having the project and the tag say the same thing for a given task being tracked. You'll
    likely need to change this behavior.

    This is the class that actually creates the widget. It inherits ui.View, a built in Pythonista object.

    Because of the limitations of the widget view in iOS, this is a little odd.

    First of all, there are really two views here: the timer selection view and the task selection view.
    Normally these would be separate, but as there is no convenient way to open a sheet or switch views in the widget,
    this was simpler.

    Secondly, Pythonista widgets crash when there are constants, so all variables are incorporated in the view object.
    """
    def __init__(self, cols, *args, **kwargs):
        """
        Initialize all the variables, most importantly, initialize all of the viewable elements that will comprise the
        widget.

        :param cols: How many columns should be in the timer grid? Two to four suggested. Modify this by modifying the
        COLS cariable above.
        :param args: extra arguments can be passed, can be accessed through an indexed list, we won't need this
        :param kwargs: extra arguments can be passed with keywords, which can then be used to access them,
        we won't need this
        """
        # Create an API variables object so we can access all of the variables from Toggl and Todoist
        self.api_vars = ApiVariables()

        # Setting up to craete the buttons to start the various timers, we need to do this here so we know how much
        # vertical space the widget will need.
        self.cols = cols
        self.row_height = 55
        # Create a list of dictionaries, one for each timer, that includes the Toggl project name, id, and color
        self.timers = [{'title': p['name'], 'pid': p['id'], 'color': p['hex_color']}
                       for p in self.api_vars.toggl_projects]
        # This sets the size of the widget, a frame size is set by (top right x, top right y, width, height)
        super().__init__(self,
                         frame=(0, 0, 300, ceil(len(self.timers) / self.cols) * self.row_height + 50), *args, **kwargs)

        # ---TIMER SELECTION VIEW--- #

        # Creating the elements for the currently running timer, at the top of the widget

        # This will be set to the color of the project of the currently running Toggl timer, set color to a
        # placeholder
        self.current_color = ui.Label(title='', bg_color='#5f5f5f')
        self.add_subview(self.current_color)
        # This will be set to the name of the project of the currently running Toggl timer set no text displayed
        self.current_timer_name = ui.Label(text='', text_color='#fff', alignment=ui.ALIGN_CENTER)
        self.add_subview(self.current_timer_name)
        # This will be set to the time elapsed of the currently running Toggl timer, this button must be tapped to
        # update the elapsed time, set color to a placeholder
        self.current_time = ui.Button(title='', action=self.update_current_timer,
                                      bg_color='#fff', tint_color='#000000', corner_radius=9)
        self.add_subview(self.current_time)

        # Fill in placeholders and missing text values
        self.update_current_timer()

        # Actually creating the buttons, using the dictionaries created above, and adding them as subviews
        # '#55bcff' is the default color if for come reason none is provided.
        self.buttons = []
        for s in self.timers:
            btn = ui.Button(title=s['title'], pid=s['pid'], action=self.timer_selected,
                            bg_color=s.get('color', '#55bcff'), tint_color='#fff', corner_radius=9)
            self.add_subview(btn)
            self.buttons.append(btn)

        # ---TASK SELECTION VIEW--- #

        # Should the Task Selection View be displaying? Default is no
        self.task_selector = False
        # This variable keeps track of which Toggl project we've selected
        self.pid = -1
        # These variables are for keeping track of the list of tasks associated with the currently selected Toggl
        # Project, again, these are associated like this: Toggl Project ---> Todoist Label of the same name
        self.tasks = []
        self.task_names = []

        # This is a big button that allows you to click anywhere outside the task selector window and associated
        # buttons to 'close' the Task Selection View (really just changes the value of self.task_selector)
        self.exit_task_selector = ui.Button(title='', action=self.task_selector_exit,
                                            bg_color='#818181', tint_color='#fff')
        self.add_subview(self.exit_task_selector)

        # The table that will display the list of tasks
        self.task_list = ui.TableView(action=self.select_task,
                                      data_source=ui.ListDataSource(items=self.task_names), corner_radius=10)
        self.add_subview(self.task_list)

        # The button to select a task, it will be red anf have a plus sign inside
        self.add = ui.Button(title='+', action=self.select_task,
                             bg_color='#ea0000', tint_color='#fff', corner_radius=20)
        self.add_subview(self.add)

        # The buttons for page navigation, gray, with arrows in the direction they page
        self.next_page = ui.Button(title='>', change=1, action=self.change_page,
                                   bg_color='#5f5f5f', tint_color='#fff', corner_radius=20)
        self.last_page = ui.Button(title='<', change=-1, action=self.change_page,
                                   bg_color='#5f5f5f', tint_color='#fff', corner_radius=20)
        self.add_subview(self.next_page)
        self.add_subview(self.last_page)

        # The current page we're displaying
        self.page = 0
        # Tasks per page, with is a function of how vertically tall the table view is. It is hardcoded because I'm lazy.
        self.tasks_per_page = 8

    def layout(self):
        """
        This paints the screen with the current viewable objects, its all fidgety graphics stuff
        """
        if self.task_selector:
            self.current_color.alpha = 0
            self.current_time.alpha = 0
            self.current_timer_name.alpha = 0
            for i, btn in enumerate(self.buttons):
                btn.alpha = 0
            self.exit_task_selector.frame = ui.Rect(0, 0, self.width, self.height)
            self.exit_task_selector.alpha = .5
            th = self.height - 50
            self.task_list.frame = ui.Rect(30, 10, self.width-60, th+30)
            self.task_list.alpha = 1
            self.add.frame = ui.Rect(self.width-45, th+5, 40, 40)
            self.add.alpha = 1
            self.last_page.frame = ui.Rect(5, th-45, 40, 40)
            self.next_page.alpha = 1
            self.next_page.frame = ui.Rect(5, th+5, 40, 40)
            self.last_page.alpha = 1
        else:
            self.update_current_timer()
            self.current_color.frame = ui.Rect(0, 0, self.width, 50)
            self.current_color.alpha = 1
            self.current_time.frame = ui.Rect(self.width-70, 5, 65, 40)
            self.current_time.alpha = 1
            self.current_timer_name.frame = ui.Rect(0, 0, self.width, 50)
            self.current_timer_name.alpha = 1
            bw = self.width / self.cols
            bh = self.row_height
            for i, btn in enumerate(self.buttons):
                btn.frame = ui.Rect(i % self.cols * bw, i//self.cols * bh + 50, bw, bh).inset(2, 2)
                btn.alpha = 1 if btn.frame.max_y < self.height else 0
            self.exit_task_selector.alpha = 0
            self.task_list.alpha = 0
            self.add.alpha = 0
            self.next_page.alpha = 0
            self.last_page.alpha = 0

    # --UPDATES-- #

    # ---TASK SELECTION VIEW--- #

    def update_task_selector(self, label, pid):
        """
        This button updates the relevant variables for the Task Selection View
        :param label: this is the Toggl project linked to the Todoist label
        :param pid: this is the Toggl pid
        """
        # Reset page to 0
        self.page = 0
        # Set new pid
        self.pid = pid
        # From the full list of tasks (pulled straight from the Todoist API), get the ones with the appropriate label
        self.tasks = [t for t in self.api_vars.tasks if label in [self.api_vars.labels[l] for l in t.labels]]
        # Sort by project, then task content, alphabetically
        self.tasks.sort(key=lambda t: (t.project.name, t.content))
        # Create a list of task names (the above is a list of objects), prepend '#Project' for each task
        self.task_names = [" #" + t.project.name + " " + t.content for t in self.tasks]
        # Update the tasks currently in the page
        self.update_page()

    def update_page(self):
        """
        Update the tasks currently in the page
        """
        # Only display tasks_per_page tasks at a time
        start, end = self.page * self.tasks_per_page, (self.page + 1) * self.tasks_per_page
        self.task_list.data_source = ui.ListDataSource(items=self.task_names[start:end])

    # --BUTTONS-- #
    # All of these functions must be set up to take a 'sender' as a parameter, because when buttons call them,
    # the button passes itself as a parameter. None but

    # ---TIMER SELECTION VIEW--- #
    def update_current_timer(self, sender=None):
        """
        Triggered on tapping the current_time button, and on every layout, this updates the current timer section at the
        top of the Task Selection View, pulling the new current timer, and adjusting the color, project and time elapsed
        accordingly.
        :param sender: the button that was pressed, not used
        """
        # Get the elapsed time
        current_timer = toggl.currentRunningTimeEntry()['data']
        start_time = str(current_timer['start'].split('+')[0])
        current_time = datetime.datetime.utcnow() - datetime.datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S")
        self.current_time.title = ':'.join(str(current_time).split(':')[:2])

        # Get the color and project title
        for p in self.api_vars.toggl_projects:
            if p['id'] == current_timer['pid']:
                self.current_color.bg_color = p['hex_color']
                self.current_timer_name.text = p['name']

    def timer_selected(self, sender):
        """
        Triggered on pressing a timer button, this either opens the Task Selection View or if there are no tasks,
        simply starts a timer.
        :param sender: the button that was pressed, includes the name of the project selected (title) and the associated
        project id (pid)
        :return:
        """
        self.update_task_selector(sender.title, sender.pid)
        # If there are any tasks in this label, open the Task Selection View, otherwise just start a timer with no
        # description
        if len(self.tasks) > 0:
            self.task_selector = True
            self.layout()
        else:
            self.start_timer('', [], sender.pid)

    # ---TASK SELECTION VIEW--- #

    def select_task(self, sender):
        """
        Triggered by the add button, starts a timer with the description of the task, tagged with the labels of the
        task, and the project of the task
        :param sender: the button that was pressed, not used
        :return:
        """
        # Get the correct task from the list, with associated information
        task = self.tasks[self.task_list.selected_row[1] + self.page * self.tasks_per_page]
        tags = [task.project.name] + [self.api_vars.labels[l] for l in task.labels]
        task = task.content
        # Start the timer
        self.start_timer(task, tags, self.pid)
        # Switch back to the Timer Selection View
        self.task_selector = False
        self.layout()

    def change_page(self, sender):
        """
        Triggered by the next_page and last_page buttons, display either the next or last page accordingly
        :param sender: the button that was pressed, used to get the int change, which indicates which direction to turn
        the page in
        :return:
        """
        page = self.page + sender.change
        # Can't last_page if you're on the first page
        self.page = page if page > -1 else 0
        # Update what is displaying
        self.update_page()
        self.layout()

    def task_selector_exit(self, sender):
        """
        If the user clicks outside the Task Selection View elements, switch to the Timer Selection View
        :param sender: the button that was pressed, not used
        :return:
        """
        self.task_selector = False
        self.layout()

    # --UTILITIES-- #

    def start_timer(self, desc, tags, pid):
        """
        Start a Toggl timer
        :param desc: string, the description to give the new timer
        :param tags: list of strings, the tags
        :param pid:  int, the pre-existing pid
        """
        # remove 'ing' tags
        tags = [t for t in tags if 'ing' not in t]
        # If a tag isn't already in Toggl, add it
        for tag in tags:
            if tag not in self.api_vars.toggl_tags:
                toggl.createTag(tag, self.api_vars.toggl_workspaces[0]['id'])
        # Start the timer
        toggl.startTimeEntry(desc, tags, pid)


class ApiVariables:
    """
    This class holds all of the API updated variables for easy access and updates.
    """
    def __init__(self):
        """
        Initialize all the variables to be tracked and pull from their APIs
        """
        self.toggl_workspaces = []
        self.toggl_projects = []
        self.toggl_tags = []
        self.labels = []
        self.tasks = []
        self.update_api_variables()

    def update_api_variables(self):
        """
        Pull updated data from Toggl and Todoist APIs and update variables accordingly
        """
        # Toggl
        self.toggl_workspaces = toggl.getWorkspaces()
        self.toggl_projects = []
        for w in self.toggl_workspaces:
            # Get Toggl projects, and if actual_hours not in project, add it
            self.toggl_projects += [p if 'actual_hours' in p else {**p, **{'actual_hours': 0}}
                                    for p in toggl.getWorkspaceProjects(w['id'])]
        # sort projects by hours logged
        self.toggl_projects = sorted(self.toggl_projects, key=itemgetter('actual_hours', 'color'), reverse=True)
        self.toggl_tags = [t['name'] for w in self.toggl_workspaces for t in toggl.getWorkspaceTags(w['id'])]

        # Todoist
        self.labels = todoist.get_labels()
        self.labels = {l.id: l.name for l in self.labels}
        # PyTodoist has an get_uncompleted_tasks, but its very bad. Unclear why is exists: in any case, this seems to
        # work correctly
        self.tasks = todoist.get_tasks()


def main():
    # Get the current widget
    widget_name = __file__ + str(os.stat(__file__).st_mtime)
    v = appex.get_widget_view()
    # Only update the widget if the widget isn't displaying
    if v is None or v.name != widget_name:
        v = TimerView(COLS)
        v.name = widget_name
        appex.set_widget_view(v)

if __name__ == '__main__':
    main()
