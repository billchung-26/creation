let players = [
  { name: "Stephen Curry", pts: 21, reb: 0, ast: 7, stl: 0, blk: 2 },
  { name: "Klay Thompson", pts: 30, reb: 6, ast: 3, stl: 3, blk: 0 },
  { name: "Draymond Green", pts: 16, reb: 10, ast: 0, stl: 0, blk: 5 },
  { name: "Chris Paul", pts: 6, reb: 0, ast: 7, stl: 6, blk: 0 },
  { name: "Kevon Looney", pts: 21, reb: 4, ast: 3, stl: 0, blk: 0 }
];

const dataPanel = document.querySelector("#data-panel");
const player = players[2];

// write your code here

function displayPlayerList(players) {
  let htmlContent = "";
  players.forEach((player) => {
    htmlContent += "<tr>";
    for (let key in player) {
      if (key === "name") {
        htmlContent += `<th>${player[key]}</th>`;
      } else if (key !== "name") {
        htmlContent += ` <th> 
          <span>${player[key]}</span> 
          <i class="fa fa-plus-circle up"></i> 
          <i class="fa fa-minus-circle down"></i>
        </th>`;
      }
    }
    htmlContent += "</tr>";
  });
  console.log(player);
  dataPanel.innerHTML = htmlContent;
}

displayPlayerList(players);

let addBtn = document.querySelector("#data-panel");

addBtn.addEventListener("click", function (event) {
  let target = event.target;
  const scoreBoard = target.parentElement.children[0];
  let scoreBoardNumber = parseInt(scoreBoard.innerText);
  if (target.classList.contains("up")) {
    scoreBoardNumber += 1;
  } else if (target.classList.contains("down")) {
    if (scoreBoardNumber > 0) {
      scoreBoardNumber -= 1;
    }
  }
  scoreBoard.innerText = scoreBoardNumber;
});