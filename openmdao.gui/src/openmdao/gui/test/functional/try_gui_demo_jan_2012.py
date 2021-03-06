'''
  Run the use case described on
    https://docs.google.com/document/d/16m74ZhD1_TpgmGH_RPTUGthIMCGNsxRhJOpucbDX_4E/edit?hl=en_US
'''
import time
from nose.tools import eq_ as eq
from nose.tools import with_setup
from openmdao.gui.test.functional.pageobjects.openmdao_login import LoginPageObject

import setup_server_and_browser

@with_setup(setup_server_and_browser.setup_server, setup_server_and_browser.teardown_server)
def test_generator():
    for browser in setup_server_and_browser.browsers :
        for _test in [ _test_gui_demo_jan_2012, ]:
            yield _test, browser

def _test_gui_demo_jan_2012(browser):
    gui_demo_jan_2012(browser)

def gui_demo_jan_2012(browser):

    ########## Login ##########
    login_page = LoginPageObject(browser, setup_server_and_browser.port)
    login_page.go_to()
    eq( "Login", login_page.page_title )

    projects_page = login_page.login_successfully("herb", "herb" )
    eq( "Projects", projects_page.page_title )
    
    ########## New Project ##########
    new_project_page = projects_page.new_project()
    assert new_project_page.page_title.startswith( "New Project" )
    
    new_project_name = new_project_page.get_random_project_name()
    new_project_description = "A project generated by a test " \
                "script which automates the GUI demo posted in Jan 2012"
    new_project_version = "initial version"
    new_project_shared = True
    project_info_page = new_project_page.create_project(
        new_project_name,
        new_project_description, 
        new_project_version, 
        new_project_shared
        )

    project_info_page.assert_on_correct_page()
    eq( new_project_name, project_info_page.page_title )

    ########## Go into Workspace ##########
    workspace_page = project_info_page.load_project_into_workspace()
    workspace_page.assert_on_correct_page()

    ########## Assert initial state ##########
    # Check to see if Objects has "top" and "driver" elements.
    #   There are two li tags with path values of "top" and "top.driver"
    #   with the latter inside the former.
    # They are inside a div with an id of otree
    object_names = workspace_page.get_objects_attribute("path")
    eq( sorted( object_names ), sorted( [ "top", "top.driver" ] ) )

    # Structure tab should have Driver icon
    component_names = workspace_page.get_dataflow_component_names()
    eq( sorted( component_names ), sorted( [ "top" ] ) )

    ########## New File ##########
    workspace_page.new_file( "plane.py", '''
from openmdao.main.api import Component
from openmdao.lib.datatypes.api import Float

class Plane(Component):

    x1 = Float(0.0,iotype="in")
    x2 = Float(0.0,iotype="in")
    x3 = Float(0.0,iotype="in")

    f_x = Float(0.0,iotype="out")
'''
                              )
    # Add paraboloid file
    import openmdao.examples.simple.paraboloid
    file_path = openmdao.examples.simple.paraboloid.__file__
    if file_path.endswith( ".pyc" ):
        file_path = file_path[ :-1 ]
    workspace_page.add_file( file_path )

    # import both files
    workspace_page.import_from_file( "plane.py" )
    time.sleep(2)
    workspace_page.import_from_file( "paraboloid.py" )

    workspace_page.objects_tab()

    import pdb; pdb.set_trace()

    # !!!!!! This next call is not working because the context menu
    #           is not coming up. I have no idea why. Maybe because of
    #           the upgrade to Firefox 10 again?
    workspace_page.show_structure( "top" )

    # drag over Plane and Paraboloid
    workspace_page.add_library_item_to_structure( "Plane", "plane" )
    workspace_page.add_library_item_to_structure( "Paraboloid", "paraboloid" )

    # Check to see if in the object tree, under the top, there should be
    #   driver
    #   paraboloid
    #   plane

    # Click on paraboloid in the object tree

    # under the Properties tab on the right there should be fields
    #   for editing the inputs and outputs for the paraboloid

    # link the y input of paraboloid with the f_xy output of plane

    # in the Strucure pane, the inputs come in the top of the icons
    #    and outputs on the right
    # link output of plane to input of paraboloid using drag and drop

    # Opens up the link editor window/div

    # Drag f_x on the left to y on the right

    # close the link editor window

    # Structure diagram should show this

    # put in some values for plane
    #    x1 = 5
    #    x2 = 15
    #    x3 = 12

    # go to Workflow tab

    # drag and drop plane and paraboloid from object tree into top icon

    # save the project

    # click on plane in object tree so properties are displayed
    #   in Properties tab

    # Context click on paraboloid and select Properties
    #   to bring up the window

    # Run the Project

    # The properties in the two areas should change
    #    f_x in plane is 103
    #    y in paraboloid is 103
    #    f_y in paraboloid is 21218

    #### Now run through optimizer

    # Get an optimizer over in Libraries
    #    openmdao.lib.drivers.conmindriver.CONMINdriver
    #  drag it into the Structures area in a blank space

    # name it driver - takes place of default driver

    # re-drag plane and paraboloid into top

    # Setup conmindriver ( not sure how you bring up the
    #    editor for the driver ( double click on icon? )

    # Click on Add Parameter

    # In the New Parameter window that comes up
    #    Target: plane.x3
    #    Low: 5
    #    High: 25
    #  Click on OK to dismiss that window

    # Click on Objectives tab

    # Click on Add Objective link

    # In the New Objective
    #    set to paraboloid.f_y

    # Save project

    # Close the CONMIN editor window

    # Project -> Run

    # Results changed
    #   plane.x1 is 5
    #   plane.x2 is 15
    #   plane.x3 is 5
    #   plane.f_x output is 75
    #   paraboloid.y = 75
    #   paraboloid.f_y = 11250
    

    # Just to see what gets saved
    workspace_page.save_project()
    
    projects_page_again = workspace_page.close_workspace()

    login_page_again = projects_page_again.logout()

    time.sleep(5)
    login_page_again.assert_on_correct_page()
    
