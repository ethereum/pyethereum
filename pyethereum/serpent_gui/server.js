var express         = require('express'),
    cp              = require('child_process'),
    async           = require('async'),
    _               = require('underscore'),
    fs              = require('fs');

var eh = function(fail, success) {
    return function(err, res) {
        if (err) {
            console.log('e',err,'f',fail,'s',success);
            if (fail) { fail(err); }
        }
        else {
            success.apply(this,Array.prototype.slice.call(arguments,1));
        }
    };
};
var mkrespcb = function(res,code,success) {
    return eh(function(e) { res.json(e,code); },success);
}

var app = express();

app.configure(function(){                                                                 
    app.set('views',__dirname + '/views');                                                  
    app.set('view engine', 'jade'); app.set('view options', { layout: false });             
    app.use(express.bodyParser());                                                          
    app.use(express.cookieParser());                                                     
    app.use(app.router);                                                                    
    app.use(express.static(__dirname + '/public'));                                         
});

app.get('/compile',function(req,res) {
    var filename = '/tmp/'+Math.random()
    console.log(req.param('data').replace(/\\n/g,'\n').replace('\\plus','+'))
    fs.writeFile(filename,req.param('data').replace(/\\n/g,'\n').replace('\\plus','+'),mkrespcb(res,400,function() {
        cp.exec('python /root/compiler/cllcompiler.py '+filename,mkrespcb(res,400,function(r) {
	    li = r.lastIndexOf('\n')
	    li2 = r.substring(0,li).lastIndexOf('\n')
	    res.json(r.substring(li2+1,li));
        }))
    }))
});

app.get('/',function(req,res) {                                                           
    res.render('compile.jade',{});                                                           
});

app.listen(3000);

return app;

