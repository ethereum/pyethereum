#!/bin/bash

secGroup="sg-f4391893"
ami="ami-8bae5feb"
keyName="piper"
keyLocation="/Users/piper/.ssh/piper_aws.pem"

instance_id=$(aws --region 'us-west-2' ec2 run-instances --key-name $keyName --security-group-ids $secGroup --instance-type t2.nano --image-id $ami --subnet-id subnet-c3ddd4a6 | awk '/INSTANCE/{print $2}') 
echo $instance_id

sleep 30

name=$(aws ec2 describe-instances $instance_id | awk '/INSTANCE/{print $4}') 
echo $name

ssh -i $keyLocation  ubuntu@$name -o StrictHostKeyChecking=no


