package ru.ticket.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;

/** Explicit read-only check against the configured public Commons gateway, no payload logging. */
class WalkMcpAudit {
  public static void main(String[] args) throws Exception {
    ((ch.qos.logback.classic.Logger)org.slf4j.LoggerFactory.getLogger("io.modelcontextprotocol")).setLevel(ch.qos.logback.classic.Level.OFF);
    var mapper=new ObjectMapper();
    try(var client=McpClientFactory.create(mapper,"https://gateway.pipeworx.io/commons-wikimedia/mcp")){
      var beans=new DefaultListableBeanFactory();beans.registerSingleton("client",client);
      var commons=new PipeworxCommonsMcpClient(beans.getBeanProvider(io.modelcontextprotocol.client.McpSyncClient.class),mapper);
      var images=commons.searchByName("Eiffel Tower",2.2945,48.8584,500,1);
      System.out.println("commonsImages="+images.size());
      for(var image:images)System.out.println("license="+image.license()+" source="+image.pageUrl()+" image="+image.imageUrl());
    }
  }
}
