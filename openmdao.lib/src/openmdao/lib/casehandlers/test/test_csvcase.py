"""
Test for CSVCaseRecorder and CSVCaseIterator.
"""
import os
import StringIO
import unittest


from openmdao.lib.casehandlers.api import CSVCaseIterator, CSVCaseRecorder, \
                                          ListCaseIterator, ListCaseRecorder, \
                                          DumpCaseRecorder
from openmdao.lib.datatypes.api import Array, Str, Slot
from openmdao.lib.drivers.api import SimpleCaseIterDriver, CaseIteratorDriver
from openmdao.main.api import Component, Assembly, Case, set_as_top
from openmdao.main.numpy_fallback import array
from openmdao.test.execcomp import ExecComp


class CSVCaseRecorderTestCase(unittest.TestCase):

    def setUp(self):
        self.top = top = set_as_top(Assembly())
        driver = top.add('driver', SimpleCaseIterDriver())
        top.add('comp1', ExecComp(exprs=['z=x+y']))
        top.add('comp2', ExecComp(exprs=['z=x+1']))
        top.connect('comp1.z', 'comp2.x')
        top.comp1.add('a_string', Str("Hello',;','", iotype='out'))
        top.comp1.add('a_array', Array(array([1.0, 3.0, 5.5]), iotype='out'))
        top.comp1.add('x_array', Array(array([1.0, 1.0, 1.0]), iotype='in'))
        driver.workflow.add(['comp1', 'comp2'])
        
        # now create some Cases
        outputs = ['comp1.z', 'comp2.z', 'comp1.a_string', 'comp1.a_array[2]']
        cases = []
        for i in range(10):
            inputs = [('comp1.x', i+0.1), ('comp1.y', i*2 + .1), ('comp1.x_array[1]', 99.88)]
            cases.append(Case(inputs=inputs, outputs=outputs, label='case%s'%i))
        driver.iterator = ListCaseIterator(cases)
        
        self.filename = "openmdao_test_csv_case_iterator.csv"
        
    def tearDown(self):
        
        if os.path.exists(self.filename):
            os.remove(self.filename)        
        pass

    def test_inoutCSV(self):
        """This test runs some cases, puts them in a CSV file using a CSVCaseRecorder,
        then runs the model again using the same cases, pulled out of the CSV file
        by a CSVCaseIterator.  Finally the cases are dumped to a string after
        being run for the second time.
        """
        
        self.top.driver.recorders = [CSVCaseRecorder(filename=self.filename)]
        self.top.run()
        
        # now use the CSV recorder as source of Cases
        self.top.driver.iterator = self.top.driver.recorders[0].get_iterator()
        
        sout = StringIO.StringIO()
        self.top.driver.recorders = [DumpCaseRecorder(sout)]
        self.top.run()
        expected = [
            'Case: case8',
            '   uuid: ad4c1b76-64fb-11e0-95a8-001e8cf75fe',
            '   inputs:',
            '      comp1.x: 8.1',
            '      comp1.x_array[1]: 99.88',
            '      comp1.y: 16.1',
            '   outputs:',
            #"      comp1.a_list: [1, 'one', 1.0]",
            "      comp1.a_array[2]: 5.5",
            "      comp1.a_string: Hello',;','",
            '      comp1.z: 24.2',
            '      comp2.z: 25.2',
            ]
        lines = sout.getvalue().split('\n')
        for index, line in enumerate(lines):
            if line.startswith('Case: case8'):
                for i in range(len(expected)):
                    if expected[i].startswith('   uuid:'):
                        self.assertTrue(lines[index+i].startswith('   uuid:'))
                    else:
                        self.assertEqual(lines[index+i], expected[i])
                break
        else:
            self.fail("couldn't find the expected Case")
            
    def test_inoutCSV_delimiter(self):
        """Repeat test above using semicolon delimiter and ' as quote char.
        """
        
        self.top.driver.recorders = [CSVCaseRecorder(filename=self.filename, delimiter=';', \
                                                     quotechar="'")]
        self.top.run()
        
        # now use the DB as source of Cases
        self.top.driver.iterator = self.top.driver.recorders[0].get_iterator()
        
        sout = StringIO.StringIO()
        self.top.driver.recorders = [DumpCaseRecorder(sout)]
        self.top.run()
        expected = [
            'Case: case8',
            '   uuid: ad4c1b76-64fb-11e0-95a8-001e8cf75fe',
            '   inputs:',
            '      comp1.x: 8.1',
            '      comp1.x_array[1]: 99.88',
            '      comp1.y: 16.1',
            '   outputs:',
            "      comp1.a_array[2]: 5.5",
            "      comp1.a_string: Hello',;','",
            '      comp1.z: 24.2',
            '      comp2.z: 25.2',
            ]
        lines = sout.getvalue().split('\n')
        for index, line in enumerate(lines):
            if line.startswith('Case: case8'):
                for i in range(len(expected)):
                    if expected[i].startswith('   uuid:'):
                        self.assertTrue(lines[index+i].startswith('   uuid:'))
                    else:
                        self.assertEqual(lines[index+i], expected[i])
                break
        else:
            self.fail("couldn't find the expected Case")
            
            
    def test_CSVCaseIterator_read_external_file_with_header(self):
        
        # Without a label column
        
        csv_data = ['"comp1.x", "comp1.y", "comp2.b_string"\n',
                    '33.5, 76.2, "Hello There"\n'
                    '3.14159, 0, "Goodbye z"\n'
                    ]
        
        outfile = open(self.filename, 'w')
        outfile.writelines(csv_data)
        outfile.close()
        
        self.top.comp2.add('b_string', Str("Hello',;','", iotype='in'))
        
        
        sout = StringIO.StringIO()
        self.top.driver.iterator = CSVCaseIterator(filename=self.filename)
        self.top.driver.recorders = [DumpCaseRecorder(sout)]
        self.top.run()
        
        self.assertEqual(self.top.comp1.x, 3.14159)
        self.assertEqual(self.top.comp1.y, 0.0)
        self.assertEqual(self.top.comp2.b_string, "Goodbye z")
        
        # With a label column
        
        csv_data = ['"label", "comp1.x", "comp1.y", "comp2.b_string"\n',
                    '"case1", 33.5, 76.2, "Hello There"\n'
                    ]
        
        outfile = open(self.filename, 'w')
        outfile.writelines(csv_data)
        outfile.close()
        
        self.top.driver.iterator = CSVCaseIterator(filename=self.filename)
        self.top.driver.recorders = [ListCaseRecorder()]
        self.top.run()
        
        it = self.top.driver.recorders[0].get_iterator()
        case1 = it.pop()
        self.assertEqual(case1.label, 'case1')
        
    def test_CSVCaseIterator_read_external_file_without_header(self):
        
        # Without a label column
        
        csv_data = ['33.5, 76.2, "Hello There"\n'
                    '3.14159, 0, "Goodbye z"\n'
                    ]
        
        outfile = open(self.filename, 'w')
        outfile.writelines(csv_data)
        outfile.close()
        
        header_dict = { 0 : "comp1.x",
                        1 : "comp1.y",
                        2 : "comp2.b_string",
                        }
        
        self.top.comp2.add('b_string', Str("Hello',;','", iotype='in'))
        
        
        sout = StringIO.StringIO()
        self.top.driver.iterator = CSVCaseIterator(filename=self.filename, \
                                                   headers=header_dict)
        self.top.driver.recorders = [DumpCaseRecorder(sout)]
        self.top.run()
        
        self.assertEqual(self.top.comp1.x, 3.14159)
        self.assertEqual(self.top.comp1.y, 0.0)
        self.assertEqual(self.top.comp2.b_string, "Goodbye z")
        
        # With a label column
        
        csv_data = ['"case1", 33.5, 76.2, "Hello There"\n'
                    ]
        
        header_dict = { 0 : "label",
                        1 : "comp1.x",
                        2 : "comp1.y",
                        3 : "comp2.b_string",
                        }
        
        outfile = open(self.filename, 'w')
        outfile.writelines(csv_data)
        outfile.close()
        
        self.top.driver.iterator = CSVCaseIterator(filename=self.filename, \
                                                   headers=header_dict)
        self.top.driver.recorders = [ListCaseRecorder()]
        self.top.run()
        
        it = self.top.driver.recorders[0].get_iterator()
        case1 = it.pop()
        self.assertEqual(case1.label, 'case1')
        
        
    def test_CSVCaseRecorder_messages(self):
        
        self.top.comp2.add('a_slot', Slot(object, iotype='in'))
        self.top.driver.recorders = [CSVCaseRecorder(filename=self.filename)]

        case = Case(inputs=[('comp2.a_slot', None)])

        try:
            self.top.driver.recorders[0].record(case)
        except ValueError, err:
            msg = "CSV format does not support variables of type <type 'NoneType'>"
            self.assertEqual(msg, str(err))
        else:
            self.fail('ValueError Expected')
        

if __name__ == '__main__':
    unittest.main()