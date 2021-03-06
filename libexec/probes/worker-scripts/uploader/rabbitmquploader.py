from uploader import *
# Need to push to Rabbit mq
import pika

class RabbitMQUploader(Uploader):
    
    def __init__(self, start = 1600, connect = 'iut2-net3.iu.edu', metricName='org.osg.general-perfsonar-simple.conf'):
        Uploader.__init__(self, start, connect, metricName)
        self.maxMQmessageSize =  self.readConfigFile('mq-max-message-size')
        self.username = self.readConfigFile('username')
        self.password = self.readConfigFile('password')
        self.rabbithost = self.readConfigFile('rabbit_host')
        self.virtual_host = self.readConfigFile('virtual_host')
        self.queue = self.readConfigFile('queue')
        self.exchange = self.readConfigFile('exchange')
        self.routing_key = self.readConfigFile('routing_key')
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameters = pika.ConnectionParameters(host=self.rabbithost,virtual_host=self.virtual_host,credentials=credentials)
            self.connection = pika.BlockingConnection(parameters)
        except Exception as e:
            self.add2log("Unable to create dirq channgel, exception was %s, " % (e))


    # Publish summaries to Mq
    def publishSToMq(self, arguments, event_types, summaries, summaries_data):
        # the max size limit in KB but python expects it in bytes
        size_limit = self.maxMQmessageSize * 1000
        for event in summaries_data.keys():
            if not summaries_data[event]:
                continue
            msg_head = { 'input-source' : arguments['input_source'],
                         'input-destination' : arguments['input_destination'],
                         'event-type' : event,
                         'rsv-timestamp' : "%s" % time.time(),
                         'summaries' : 1,
                         'destination' : '/topic/perfsonar.summary.' + event }
            msg_body = { 'meta': arguments }
            msg_body['summaries'] = summaries_data[event]
            #msg = Message(body=json.dumps(msg_body), header=msg_head)
            self.SendMessagetoMQ(msg_body)

    def SendMessagetoMQ(self, msg_body):
        # the max size limit in KB but python expects it in bytes                                                                           
        size_limit = self.maxMQmessageSize * 1000
        channel = self.connection.channel()
        channel.queue_declare(queue=self.queue,durable=True)
        ch_prop = pika.BasicProperties(delivery_mode = 2) #Make message persistent
        size_msg = sys.getsizeof(json.dumps(msg_body))
        # if size of the message is larger than 10MB discarrd                                                                             
        if size_msg > size_limit:
            self.add2log("Size of message body bigger than limit, discarding")
            channel.close()
            return
        # add to mq                                                                                                                       
        try:
            result = channel.basic_publish(exchange = self.exchange,
                                           routing_key = self.routing_key,
                                           body = json.dumps(msg_body), 
                                           properties = ch_prop)
            if not result:
                raise Exception('Exception publishing to rabbit MQ', 'Problem publishing to mq')
        except Exception as e:
            self.add2log("ERROR: Failed to send message to mq, exception was %s" % (e))
        channel.close()

    # Publish message to Mq
    def publishRToMq(self, arguments, event_types, datapoints):
        for event in datapoints.keys():
            # filter events for mq (must be subset of the probe's filter)
            if event not in self.allowedEvents:
                continue
            # skip events that have no datapoints 
            if not datapoints[event]:
                continue
            # compose msg
            msg_head = { 'input-source' : arguments['input_source'],
                        'input-destination' : arguments['input_destination'],
                         'event-type' : event,
                         'rsv-timestamp' : "%s" % time.time(),
                         'summaries' : 0,
                         'destination' : '/topic/perfsonar.raw.' + event}
            msg_body = { 'meta': arguments }
            msg_body['datapoints'] = datapoints[event]
            self.SendMessagetoMQ(msg_body)
            

    def postData(self, arguments, event_types, summaries, summaries_data, metadata_key, datapoints):
        summary= self.summary
        disp = self.debug
        lenght_post = -1
        for event_type in datapoints.keys():
            if len(datapoints[event_type])>lenght_post:
                lenght_post = len(datapoints[event_type])
        if lenght_post == 0:
            self.add2log("No new datapoints skipping posting for efficiency")
            return
        if summaries_data:
            self.add2log("posting new summaries")
            self.publishSToMq(arguments, event_types, summaries, summaries_data)
        step_size = 100
        for step in range(0, lenght_post, step_size):
            chunk_datapoints = {}
            for event_type in datapoints.keys():
                chunk_datapoints[event_type] = {}
                if len(datapoints[event_type].keys())>0:
                    pointsconsider = sorted(datapoints[event_type].keys())[step:step+step_size]
                    for point in pointsconsider:
                        chunk_datapoints[event_type][point] = datapoints[event_type][point]
            if True:
                self.publishRToMq(arguments, event_types, chunk_datapoints)
                # Updating the checkpoint files for each host/metric and metadata
                for event_type in datapoints.keys():
                     if len(datapoints[event_type].keys()) > 0:
                         if event_type not in self.time_starts:
                             self.time_starts[event_type] = 0
                         next_time_start = max(datapoints[event_type].keys())+1
                         if next_time_start > self.time_starts[event_type]:
                             self.time_starts[event_type] = int(next_time_start)
                f = open(self.tmpDir + metadata_key, 'w')
                f.write(json.dumps(self.time_starts))
                f.close()
                self.add2log("posting NEW METADATA/DATA to esmondmq %s" % metadata_key)
                
