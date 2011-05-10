import ordereddict
import itertools
from numpy import float32, float64, int32, int64

from openmdao.main.expreval import ExprEvaluator
from openmdao.util.decorators import add_delegate

class Parameter(object): 
    
    def __init__(self, expreval, high=None, low=None, fd_step=None):
        self.low = low
        self.high = high
        self.fd_step = fd_step
        if not expreval.is_valid_assignee():
            raise ValueError("Parameter '%s' cannot be assigned to" % expreval.text)
        self._expreval = expreval

    def __str__(self):
        return self.target

    def __repr__(self): 
        return '<Parameter(target=%s,low=%s,high=%s,fd_step=%s)>'%(self.target,self.low,self.high,self.fd_step)
    
    @property
    def target(self): 
        return self._expreval.text
    
    def evaluate(self, scope=None):
        return self._expreval.evaluate(scope)
    
    def set(self, val, scope=None):
        self._expreval.set(val, scope)

    def get_metadata(self, metaname=None):
        return self._expreval.get_metadata(metaname)

class ParameterGroup(object): 
    
    def __init__(self, params):
        self._params = params[:]
            
    @property
    def targets(self): 
        return [p.target for p in self._params]
    
    def set(self, value, scope=None):
        """Set all targets to the given value."""
        for p in self._params: 
            p.set(value, scope)
            
    def evaluate(self, scope=None):
        """Return the value of the first parameter in our target list. Values of
        all of our targets are assumed to be the same.
        """
        return self._params[0].evaluate(scope)


class HasParameters(object): 
    """This class provides an implementation of the IHasParameters interface."""

    _do_not_promote = ['get_expr_depends']
    
    def __init__(self, parent):
        self._parameters = ordereddict.OrderedDict()
        self._parent = parent

    def add_parameter(self, name, low=None, high=None, fd_step=None):
        """Adds a parameter to the driver.
        
        name: string or iter of strings
            Name of the variable the driver should vary during execution.
            If an iterator of names is given, then the driver will set all names given
            to the same value whenever it varies this parameter during execution
            
        low: float (optional)
            Minimum allowed value of the parameter.
            
        high: float (optional)
            Maximum allowed value of the parameter.
            
        fd_step: float (optional)
            Step-size to use for finite difference calculation. If no value is
            given, the differentitator will use its own default
        
        If neither "low" nor "high" is specified, the min and max will
        default to the values in the metadata of the variable being
        referenced. If they are not specified in the metadata and not provided
        as arguments, a ValueError is raised.
        """
        if isinstance(name, str): 
            names = [name]
            key = name
        else: 
            names = name
            key = tuple(name)

        all_names = set(self.list_targets())
        for name in names: 
            if name in all_names: 
                self._parent.raise_exception("'%s' is already the target of a Parameter" % name,
                                             ValueError)
        parameters = []
        for name in names:
            try:
                parameter = Parameter(ExprEvaluator(name, self._parent),
                                      low=low, high=high, fd_step=fd_step)
            except Exception as err:
                self._parent.raise_exception("Can't add parameter: %s" % str(err),
                                             err.__class__)
            try:
                metadata = parameter.get_metadata()
            except AttributeError:
                self._parent.raise_exception("Can't add parameter '%s' because it doesn't exist." % name,
                                             AttributeError)
            try:
                val = parameter.evaluate()
            except Exception as err:
                self._parent.raise_exception("Can't add parameter because I can't evaluate '%s'." % name, 
                                             ValueError)
            if not isinstance(val,(float,float32,float64,int,int32,int64)):
                self._parent.raise_exception("The value of parameter '%s' must be of type float or int, but its type is '%s'." %
                                             (name,type(val).__name__), ValueError)
            
            meta_low = metadata.get('low') # this will be None if 'low' isn't there
            if low is None:
                parameter.low = meta_low
            else:  # low is not None
                if meta_low is not None and low < meta_low:
                    self._parent.raise_exception("Trying to add parameter '%s', " 
                                                 "but the lower limit supplied (%s) exceeds the " 
                                                 "built-in lower limit (%s)." % 
                                                 (name, low, meta_low), ValueError)
                parameter.low = low
    
            meta_high = metadata.get('high') # this will be None if 'high' isn't there
            if high is None:
                parameter.high = meta_high
            else:  # high is not None
                if meta_high is not None and high > meta_high:
                    self._parent.raise_exception("Trying to add parameter '%s', " 
                                                 "but the upper limit supplied (%s) exceeds the " 
                                                 "built-in upper limit (%s)." % 
                                                 (name, high, meta_high), ValueError)
                parameter.high = high
                
            values = metadata.get('values')
            if values is not None and len(values)>0:
                pass    # assume it's an Enum, so no need to set high or low
            else:
                if parameter.low is None:
                    self._parent.raise_exception("Trying to add parameter '%s', "
                                                 "but no lower limit was found and no " 
                                                 "'low' argument was given. One or the "
                                                 "other must be specified." % name,ValueError)
                if parameter.high is None: 
                    self._parent.raise_exception("Trying to add parameter '%s', "
                                                 "but no upper limit was found and no " 
                                                 "'high' argument was given. One or the "
                                                 "other must be specified." % name,ValueError)
                    
            if parameter.low > parameter.high:
                self._parent.raise_exception("Parameter '%s' has a lower bound (%s) that exceeds its upper bound (%s)" %
                                             (name, parameter.low, parameter.high), ValueError)
    
            parameter.fd_step = fd_step
            parameters.append(parameter)
        types = set([type(param.evaluate()) for param in parameters])
        if len(types) > 1: 
            self._parent.raise_exception("Can not add parameter %s because "
                             "%s are not the same type"%(tuple(orig_names)," and ".join(orig_names)))
            
        if len(parameters) == 1: #just one in there
            self._parameters[orig_names] = parameters[0]
        else: 
            self._parameters[orig_names] = ParameterGroup(parameters)
        
            
    def remove_parameter(self, name):
        """Removes the parameter with the given name."""
            
        try:
            del self._parameters[name]
        except KeyError:
            self._parent.raise_exception("Trying to remove parameter '%s' "
                                         "that is not in this driver." % (name,),
                                         AttributeError)
    def list_parameters(self):
        """Returns an alphabetized list of parameter names."""
        return sorted(self._parameters.keys())
    
    def list_targets(self):
        """Returns an alphabetized list of parameter targets, including
        all targets of ParameterGroup objects.
        """
        targets = []
        for param in self._parameters.values():
            if isinstance(param, ParameterGroup):
                targets.extend(param.targets)
            else:
                targets.append(param.target)
        return sorted(targets)
    
    def clear_parameters(self):
        """Removes all parameters."""
        self._parameters = ordereddict.OrderedDict()
        
    def get_parameters(self):
        """Returns an ordered dict of parameter objects."""
        return self._parameters

    def set_parameters(self, values): 
        """Pushes the values in the iterator 'values' into the corresponding 
        variables in the model.
        
        values: iterator
            Iterator of input values with an order defined to match the 
            order of parameters returned by the list_parameter method. 
            'values' must support the len() function.
        """
        if len(values) != len(self._parameters):
            raise ValueError("number of input values (%s) != number of parameters (%s)" % 
                             (len(values),len(self._parameters)))

        for val, param in zip(values, self._parameters.values()):
            param.set(val)

    def get_expr_depends(self):
        """Returns a list of tuples of the form (src_comp_name, dest_comp_name)
        for each dependency introduced by a parameter.
        """
        conn_list = []
        pname = self._parent.name
        for name,param in self._parameters.items():
            for cname in param.get_referenced_compnames():
                conn_list.append((pname, cname))
        return conn_list
    
