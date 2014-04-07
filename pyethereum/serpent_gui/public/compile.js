angular.module('compiler', []);

function CompilerCtrl($scope,$http) {
    window.wscope = $scope;
    $scope.submit = function() {
        console.log('compile',$scope.text.replace(/\n/g,'\\n'))
        $http.get('/compile?data='+$scope.text.replace(/\n/g,'\\n').replace('+','\\plus'))
             .success(function(r) {
		 $scope.response = r.replace(/"/g,'') 
                 $scope.error = ''
             })
             .error(function(r) {
		 $scope.error = 'compilation error'
                 $scope.response = ''
             })
    }
}
